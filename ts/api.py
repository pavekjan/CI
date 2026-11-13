"""Datova vrstva webove aplikace: vyhledani firmy, profil konkurenceschopnosti, prehled trhu.

Vsechno se pocita z lokalni SQLite databaze, kterou plni agenti (Scout/Extractor/Verifier).
ARES a zpravy se pro otevrenou firmu dotahuji zivě (s cache)."""
import re
import statistics
from collections import Counter, defaultdict
from datetime import date, timedelta

CPV_DIV = {
    "03": "Zemědělské a lesnické produkty", "09": "Paliva a energie", "14": "Těžba a kovy", "15": "Potraviny a nápoje",
    "16": "Zemědělské stroje", "18": "Oděvy a obuv", "19": "Kůže, textil, plasty", "22": "Tiskoviny", "24": "Chemické výrobky",
    "30": "Kancelářská a výpočetní technika", "31": "Elektrické stroje a přístroje", "32": "Komunikační a AV zařízení",
    "33": "Zdravotnické přístroje a léčiva", "34": "Dopravní prostředky", "35": "Bezpečnostní a obranné vybavení",
    "37": "Sport, hry, hudební nástroje", "38": "Laboratorní a optické přístroje", "39": "Nábytek a vybavení",
    "41": "Voda", "42": "Průmyslové stroje", "43": "Důlní a stavební stroje", "44": "Stavební konstrukce a materiály",
    "45": "Stavební práce", "48": "Software a informační systémy", "50": "Opravy a údržba", "51": "Instalace",
    "55": "Hotelové a stravovací služby", "60": "Dopravní služby", "63": "Podpůrné dopravní služby",
    "64": "Pošta a telekomunikace", "65": "Veřejné služby (energie, voda)", "66": "Finanční a pojišťovací služby",
    "70": "Realitní služby", "71": "Architektonické a inženýrské služby", "72": "IT služby", "73": "Výzkum a vývoj",
    "75": "Veřejná správa a obrana", "76": "Služby pro těžbu ropy a plynu", "77": "Zemědělské a zahradnické služby",
    "79": "Obchodní služby (právo, marketing, HR)", "80": "Vzdělávání", "85": "Zdravotní a sociální služby",
    "90": "Odpady, úklid, životní prostředí", "92": "Kultura, sport, rekreace", "98": "Ostatní služby",
}


def cpv_group(cpv):
    """Segment = oddil CPV (prvni 2 cislice), napr. '45 Stavební práce'."""
    if not cpv:
        return "neuvedeno"
    return f"{cpv[:2]} {CPV_DIV.get(cpv[:2], 'Ostatní')}"


from .sources.other import ares_firma, google_news
from .util import clean_ico, log, norm, parse_date, http_get

A = "API"


# ---------------------------------------------------------------- pomocne
def _median(xs):
    xs = [x for x in xs if x is not None]
    return statistics.median(xs) if xs else None


def _pc(x):
    return f"{x * 100:.0f} %"


def _pomer(cena, odhad, nazev=None):
    """Pomer vitezne ceny k predpokladane hodnote, nebo None, kdyz o cene nic nerika:
    - cena presne = odhad (zadavatel do ceny opsal predpokladanou hodnotu, typicky u ramcovych dohod),
    - ramcova dohoda (cena je strop, ne skutecny nakup),
    - zjevna chyba v radu (pomer < 5 % nebo > 20x)."""
    if not cena or not odhad:
        return None
    r = cena / odhad
    if abs(r - 1) < 0.0005 or not (0.05 <= r <= 20) or "ramcov" in norm(nazev):
        return None
    return r


NEUVEDENO = "neuvedeno"


def _clamp(x, lo=0.0, hi=100.0):
    return max(lo, min(hi, x))


def _month(d):
    return (d or "")[:7] or None


def _percentile_rank(values, v):
    """Kolik % hodnot je <= v (0-100)."""
    if not values or v is None:
        return None
    return 100.0 * sum(1 for x in values if x <= v) / len(values)


def _is_open(z, today):
    st = norm(z["stav"])
    if any(w in st for w in ("zrus", "zadan", "ukoncen", "dokoncen", "uzavren")):
        return False
    d = parse_date(z["lhuta_nabidek"])
    return bool(d and d >= today)


# ---------------------------------------------------------------- index dodavatelu
def rebuild_index(con):
    """Tabulka `dodavatele` pro rychle vyhledavani (vola se po kazde aktualizaci dat)."""
    con.execute("DELETE FROM dodavatele")
    agg = {}

    def row(ico, nazev):
        r = agg.get(ico)
        if r is None:
            r = agg[ico] = {"nazev": nazev, "vyhry": set(), "ucasti": set(), "objem": 0.0, "smluv": 0, "zname": set()}
        if nazev and (not r["nazev"] or len(nazev) > len(r["nazev"])):
            r["nazev"] = r["nazev"] or nazev
        return r

    for ico, nazev, zid, cena in con.execute("SELECT dodavatel_ico, dodavatel_nazev, zakazka_id, cena_bez_dph FROM vitezove WHERE dodavatel_ico IS NOT NULL"):
        r = row(ico, nazev)
        if zid not in r["vyhry"]:
            r["vyhry"].add(zid)
            r["objem"] += cena or 0
        r["ucasti"].add(zid)
    for ico, nazev, zid in con.execute("SELECT dodavatel_ico, dodavatel_nazev, zakazka_id FROM ucastnici WHERE dodavatel_ico IS NOT NULL"):
        row(ico, nazev)["ucasti"].add(zid)
    # zakazky, kde zdroj uvadi aspon 2 ucastniky (jen vitez = o prohrach nic nevime -> win rate by byl umele 100 %)
    z_uc = {r[0] for r in con.execute("SELECT zakazka_id FROM ucastnici GROUP BY zakazka_id HAVING COUNT(*) >= 2")}
    for r in agg.values():
        r["zname"] = r["ucasti"] & z_uc
    for ico, nazev, n in con.execute("SELECT ico, MAX(nazev), COUNT(DISTINCT smlouva_id) FROM smlouvy_strany WHERE ico IS NOT NULL GROUP BY ico"):
        row(ico, nazev)["smluv"] = n
    for ico, nazev in con.execute("SELECT ico, nazev FROM firmy"):
        if ico in agg and nazev:
            agg[ico]["nazev"] = nazev
    con.executemany("INSERT INTO dodavatele VALUES (?,?,?,?,?,?,?,?,?)",
                    [(ico, r["nazev"], norm(r["nazev"]), len(r["vyhry"]), len(r["ucasti"]), r["objem"], r["smluv"],
                      len(r["zname"]), len(r["zname"] & r["vyhry"]))
                     for ico, r in agg.items()])
    con.commit()
    log("Indexer", f"index dodavatelu: {len(agg)} firem")
    return len(agg)


# ---------------------------------------------------------------- stav dat
def stav(con, demo=False):
    one = lambda q: con.execute(q).fetchone()[0]
    rng = con.execute("SELECT MIN(datum_zahajeni), MAX(datum_zahajeni) FROM zakazky WHERE datum_zahajeni >= '2000' AND datum_zahajeni <= date('now', '+1 day')").fetchone()
    last = con.execute("SELECT konec FROM behy WHERE stav='ok' ORDER BY id DESC LIMIT 1").fetchone()
    return {
        "demo": demo,
        "zakazek": one("SELECT COUNT(*) FROM zakazky"),
        "vitezu": one("SELECT COUNT(*) FROM vitezove"),
        "dodavatelu": one("SELECT COUNT(*) FROM dodavatele"),
        "smluv": one("SELECT COUNT(*) FROM smlouvy"),
        "firem_ares": one("SELECT COUNT(*) FROM firmy"),
        "od": rng[0], "do": rng[1],
        "posledni_aktualizace": last[0] if last else None,
    }


# ---------------------------------------------------------------- vyhledavani
def hledat(con, q, ares_base=None, limit=12):
    q = (q or "").strip()
    if not q:
        return []
    out = []
    digits = re.sub(r"\D", "", q)
    if len(digits) >= 6 and len(digits) == len(q.replace(" ", "")):
        ico = clean_ico(digits)
        rows = con.execute("SELECT * FROM dodavatele WHERE ico=?", (ico,)).fetchall()
        out = [dict(r) for r in rows] or [{"ico": ico, "nazev": None, "vyhry": 0, "ucasti": 0, "objem": 0, "smluv_rs": 0}]
        return out
    words = norm(q).split()
    if not words:
        return []
    where = " AND ".join("nazev_norm LIKE ?" for _ in words)
    # bezpecnost: jen zastupne znaky ?, hodnoty jdou jako parametry (vedome potlaceni nalezu banditu, viz SECURITY.md)
    rows = con.execute(f"SELECT * FROM dodavatele WHERE {where} ORDER BY objem DESC, vyhry DESC LIMIT ?",  # nosec B608
                       [f"%{w}%" for w in words] + [limit]).fetchall()
    out = [dict(r) for r in rows]
    if len(out) < 3 and ares_base:
        for f in ares_hledat(ares_base, q):
            if not any(o["ico"] == f["ico"] for o in out):
                out.append({"ico": f["ico"], "nazev": f["nazev"], "vyhry": 0, "ucasti": 0, "objem": 0, "smluv_rs": 0, "jen_ares": True})
    return out[:limit]


def ares_hledat(base, nazev, pocet=5):
    """ARES vyhledani podle nazvu: POST .../ekonomicke-subjekty/vyhledat (nejlepsi snaha, pri chybe prazdno)."""
    try:
        from .util import session
        r = session().post(base + "vyhledat", json={"obchodniJmeno": nazev, "pocet": pocet, "start": 0},
                           headers={"Accept": "application/json"}, timeout=10)
        if r.status_code != 200:
            return []
        return [{"ico": s.get("ico"), "nazev": s.get("obchodniJmeno")} for s in r.json().get("ekonomickeSubjekty", [])]
    except Exception:
        return []


# ---------------------------------------------------------------- profil firmy
def _ares_cached(con, base, ico, online=True):
    row = con.execute("SELECT * FROM firmy WHERE ico=?", (ico,)).fetchone()
    if row and row["stazeno"] and (date.today() - date.fromisoformat(row["stazeno"][:10])).days < 30:
        return dict(row)
    if not online:
        return dict(row) if row else None
    try:
        f = ares_firma(base, ico, retries=1)
    except Exception as e:
        log(A, f"ARES {ico}: {e}")
        return dict(row) if row else None
    if f:
        f["stazeno"] = date.today().isoformat()
        con.execute("INSERT OR REPLACE INTO firmy (ico,nazev,sidlo,kraj,nace,pravni_forma,datum_vzniku,datum_zaniku,stazeno) "
                    "VALUES (:ico,:nazev,:sidlo,:kraj,:nace,:pravni_forma,:datum_vzniku,:datum_zaniku,:stazeno)", f)
        con.commit()
    return f


def _zpravy_firmy(con, base, nazev, online=True, exa_key=None):
    if not nazev:
        return []
    q = f'"{nazev}"'
    rows = con.execute("SELECT * FROM zpravy WHERE dotaz=? ORDER BY datum DESC LIMIT 8", (q,)).fetchall()
    if rows or not online:
        return [dict(r) for r in rows]
    try:
        items = google_news(base, q, limit=8, retries=1)
    except Exception:
        items = []
    if exa_key:
        from .obsidian import exa_search
        items += [{k: it[k] for k in ("titulek", "url", "datum", "zdroj")} | {"dotaz": q} for it in exa_search(exa_key, f'"{nazev}" veřejné zakázky', 5)]
    for it in items:
        con.execute("INSERT OR REPLACE INTO zpravy (url,titulek,zdroj,datum,dotaz) VALUES (:url,:titulek,:zdroj,:datum,:dotaz)", it)
    con.commit()
    return items


def _segment_stats(con, today):
    """Pro kazdy CPV segment: objem, pocet vitezstvi, median pomeru cena/odhad, objem podle dodavatele."""
    seg = defaultdict(lambda: {"objem": 0.0, "vyhry": 0, "pomery": [], "dod": defaultdict(float), "dod_n": Counter(), "nabidky": []})
    for r in con.execute("""SELECT z.cpv_hlavni, z.nazev, z.predpokladana_hodnota, z.pocet_nabidek, v.dodavatel_ico, v.dodavatel_nazev, v.cena_bez_dph
                            FROM vitezove v JOIN zakazky z ON z.id=v.zakazka_id"""):
        g = cpv_group(r["cpv_hlavni"])
        s = seg[g]
        s["vyhry"] += 1
        key = r["dodavatel_ico"] or r["dodavatel_nazev"]
        s["dod_n"][key] += 1
        s["dod"][key] += r["cena_bez_dph"] or 0
        if r["cena_bez_dph"]:
            s["objem"] += r["cena_bez_dph"]
            pm = _pomer(r["cena_bez_dph"], r["predpokladana_hodnota"], r["nazev"])
            if pm is not None:
                s["pomery"].append(pm)
        if r["pocet_nabidek"]:
            s["nabidky"].append(r["pocet_nabidek"])
    return seg


def profil(con, ico, cfg, today=None, online=True):
    today = today or date.today()
    ico = clean_ico(ico)
    z_ares = cfg["zdroje"]["ares_base"]
    firma = _ares_cached(con, z_ares, ico, online) or {}
    idx = con.execute("SELECT * FROM dodavatele WHERE ico=?", (ico,)).fetchone()
    nazev = firma.get("nazev") or (idx["nazev"] if idx else None) or ico

    wins = [dict(r) for r in con.execute("""SELECT v.cena_bez_dph, v.overeno_rs, v.smlouva_id, z.* FROM vitezove v
                                            JOIN zakazky z ON z.id=v.zakazka_id WHERE v.dodavatel_ico=?""", (ico,))]
    win_ids = {w["id"] for w in wins}
    ucasti = [dict(r) for r in con.execute("""SELECT u.nabidkova_cena, z.* FROM ucastnici u JOIN zakazky z ON z.id=u.zakazka_id
                                              WHERE u.dodavatel_ico=?""", (ico,))]
    ucast_ids = {u["id"] for u in ucasti} | win_ids
    prohry = [u for u in ucasti if u["id"] not in win_ids]
    # win rate jen ze zakazek, kde zdroj uvadi ucastniky (jinak nevime o prohrach)
    # docasna tabulka s ID zakazek firmy (misto dlouheho IN (...), ktery ma v SQLite limit)
    con.execute("CREATE TEMP TABLE IF NOT EXISTS t_ids (id TEXT PRIMARY KEY)")
    con.execute("DELETE FROM t_ids")
    con.executemany("INSERT OR IGNORE INTO t_ids VALUES (?)", [(i,) for i in ucast_ids])
    z_uc = {r[0] for r in con.execute("SELECT zakazka_id FROM ucastnici WHERE zakazka_id IN (SELECT id FROM t_ids) GROUP BY zakazka_id HAVING COUNT(*) >= 2")}
    zname = ucast_ids & z_uc
    ma_ucastniky = len(zname) > 0

    objem = sum(w["cena_bez_dph"] or 0 for w in wins)
    win_rate = (len(win_ids & zname) / len(zname)) if ma_ucastniky else None

    # ---- casova rada (mesice) ----
    by_m = defaultdict(lambda: {"vyhry": 0, "objem": 0.0, "ucasti": 0})
    for w in wins:
        m = _month(w["datum_zahajeni"])
        if m:
            by_m[m]["vyhry"] += 1
            by_m[m]["objem"] += w["cena_bez_dph"] or 0
    for u in ucasti:
        m = _month(u["datum_zahajeni"])
        if m:
            by_m[m]["ucasti"] += 1
    for w in wins:
        if w["id"] not in {u["id"] for u in ucasti}:
            m = _month(w["datum_zahajeni"])
            if m:
                by_m[m]["ucasti"] += 1
    od_m = (today - timedelta(days=730)).isoformat()[:7]  # graf: poslednich 24 mesicu (stare zaznamy jen zkresluji osu)
    mesice = [{"mesic": m, **v} for m, v in sorted(by_m.items()) if od_m <= m <= today.isoformat()[:7]]

    # ---- segmenty ----
    seg_all = _segment_stats(con, today)
    seg_f = defaultdict(lambda: {"vyhry": 0, "objem": 0.0, "pomery": []})
    for w in wins:
        g = cpv_group(w["cpv_hlavni"])
        seg_f[g]["vyhry"] += 1
        seg_f[g]["objem"] += w["cena_bez_dph"] or 0
        pm = _pomer(w["cena_bez_dph"], w["predpokladana_hodnota"], w["nazev"])
        if pm is not None:
            seg_f[g]["pomery"].append(pm)
    segmenty = []
    for g, s in sorted(seg_f.items(), key=lambda kv: -kv[1]["objem"]):
        tot = seg_all[g]["objem"] or 0
        ranked = sorted(seg_all[g]["dod"].items(), key=lambda kv: (-kv[1], -seg_all[g]["dod_n"][kv[0]]))
        poradi = next((i + 1 for i, (k, _) in enumerate(ranked) if k == ico), None) if g != NEUVEDENO else None
        segmenty.append({"segment": g, "vyhry": s["vyhry"], "objem": s["objem"],
                         "podil": (s["objem"] / tot) if tot and g != NEUVEDENO else None, "poradi": poradi, "dodavatelu": len(ranked),
                         "median_pomer": _median(s["pomery"]), "trh_median_pomer": _median(seg_all[g]["pomery"]),
                         "trh_objem": tot})
    # "neuvedeno" (zakazky bez CPV) neni segment - nepocitat do rivalu, poradi ani prilezitosti
    hlavni_seg = [s["segment"] for s in segmenty if s["segment"] != NEUVEDENO][:3]

    # ---- klienti (zadavatele) ----
    kl = defaultdict(lambda: {"nazev": None, "vyhry": 0, "objem": 0.0})
    for w in wins:
        k = kl[w["zadavatel_ico"] or w["zadavatel_nazev"]]
        k["nazev"] = k["nazev"] or w["zadavatel_nazev"] or w["zadavatel_ico"]
        k["vyhry"] += 1
        k["objem"] += w["cena_bez_dph"] or 0
    klienti = sorted(({"ico": i, **v} for i, v in kl.items()), key=lambda k: -k["objem"])
    shares = [k["objem"] / objem for k in klienti] if objem else []
    hhi = sum(s * s for s in shares) if shares else None

    # ---- ceny ----
    ceny = [{"nazev": w["nazev"], "odhad": w["predpokladana_hodnota"], "cena": w["cena_bez_dph"],
             "pomer": _pomer(w["cena_bez_dph"], w["predpokladana_hodnota"], w["nazev"]), "segment": cpv_group(w["cpv_hlavni"])}
            for w in wins if _pomer(w["cena_bez_dph"], w["predpokladana_hodnota"], w["nazev"]) is not None]
    med_pomer = _median([c["pomer"] for c in ceny])
    # vazeny trzni median ve stejnych segmentech
    trh_pomery = [p for g in seg_f if g != NEUVEDENO for p in seg_all[g]["pomery"]]
    trh_med_pomer = _median(trh_pomery)

    # ---- konkurence: prime souboje (spolecne zakazky) ----
    h2h = defaultdict(lambda: {"nazev": None, "stretu": 0, "my_vyhra": 0, "oni_vyhra": 0})
    if ucast_ids:
        winners = defaultdict(set)
        for r in con.execute("SELECT zakazka_id, dodavatel_ico FROM vitezove WHERE zakazka_id IN (SELECT id FROM t_ids)"):
            winners[r[0]].add(r[1])
        others = defaultdict(set)
        for r in con.execute("SELECT zakazka_id, dodavatel_ico, dodavatel_nazev FROM ucastnici WHERE zakazka_id IN (SELECT id FROM t_ids)"):
            if r[1] and r[1] != ico:
                others[r[0]].add(r[1])
                h2h[r[1]]["nazev"] = h2h[r[1]]["nazev"] or r[2]
        for r in con.execute("SELECT zakazka_id, dodavatel_ico, dodavatel_nazev FROM vitezove WHERE zakazka_id IN (SELECT id FROM t_ids)"):
            if r[1] and r[1] != ico:
                others[r[0]].add(r[1])
                h2h[r[1]]["nazev"] = h2h[r[1]]["nazev"] or r[2]
        for zid, os_ in others.items():
            for o in os_:
                h2h[o]["stretu"] += 1
                if ico in winners[zid]:
                    h2h[o]["my_vyhra"] += 1
                if o in winners[zid]:
                    h2h[o]["oni_vyhra"] += 1
    nazvy = {r["ico"]: r["nazev"] for r in con.execute("SELECT ico, nazev FROM dodavatele")}
    souboje = sorted(({"ico": k, "nazev": nazvy.get(k) or v["nazev"] or k, **{x: v[x] for x in ("stretu", "my_vyhra", "oni_vyhra")}}
                      for k, v in h2h.items()), key=lambda s: (-s["stretu"], -s["oni_vyhra"]))[:15]
    # rivalove v segmentech (i bez dat o ucastnicich)
    riv = defaultdict(float)
    riv_n = Counter()
    for g in hlavni_seg:
        for k, v in seg_all[g]["dod"].items():
            if k != ico:
                riv[k] += v
                riv_n[k] += seg_all[g]["dod_n"][k]
    rivalove = [{"ico": k, "nazev": nazvy.get(k) or k, "objem": v, "vyhry": riv_n[k]}
                for k, v in sorted(riv.items(), key=lambda kv: (-kv[1], -riv_n[kv[0]]))
                if k and re.fullmatch(r"\d{8}", str(k))][:10]

    # ---- regiony ----
    regiony = Counter(w["kraj"] or "neuvedeno" for w in wins).most_common()

    # ---- konkurencni intenzita ----
    nab = [w["pocet_nabidek"] for w in wins if w["pocet_nabidek"]]
    jedna = sum(1 for n in nab if n == 1)

    # ---- trend: poslednich 6 mesicu vs predchozich 6 ----
    t6 = (today - timedelta(days=183)).isoformat()
    t12 = (today - timedelta(days=366)).isoformat()
    nove = sum(1 for w in wins if (w["datum_zahajeni"] or "") >= t6)
    stare = sum(1 for w in wins if t12 <= (w["datum_zahajeni"] or "") < t6)

    # ---- skore konkurenceschopnosti ----
    slozky = []
    # 1 uspesnost
    if win_rate is not None and len(zname) >= 3:
        # trzni srovnani jen z firem, u kterych zdroj uvadi ucastniky (jinak by win rate byl umele 100 %)
        rates = [r[0] / r[1] for r in con.execute("SELECT vyhry_zname, ucasti_zname FROM dodavatele WHERE ucasti_zname >= 3")]
        trh_wr = _median(rates)
        sc = _clamp(50 + (win_rate - (trh_wr or 0)) * 150)
        slozky.append({"klic": "uspesnost", "nazev": "Úspěšnost v soutěžích", "vaha": 25, "skore": round(sc),
                       "vysvetleni": f"Win rate {_pc(win_rate)} ze {len(zname)} soutěží se známými účastníky; medián trhu {_pc(trh_wr)}." if trh_wr is not None else f"Win rate {_pc(win_rate)}."})
    elif ucast_ids:
        slozky.append({"klic": "uspesnost", "nazev": "Úspěšnost v soutěžích", "vaha": 25, "skore": None,
                       "vysvetleni": "Data o neúspěšných nabídkách chybějí (u části zakázek je zdroj neuvádí) – nelze spočítat."})
    # 2 trzni pozice
    seg_cpv = [s for s in segmenty if s["segment"] != NEUVEDENO]
    if seg_cpv:
        podily = [(s["podil"] or 0, s["objem"]) for s in seg_cpv if s["trh_objem"]]
        wsum = sum(o for _, o in podily) or 1
        vazeny = sum(p * o for p, o in podily) / wsum
        objemy = [r[0] for r in con.execute("SELECT objem FROM dodavatele WHERE objem > 0")]
        pr = _percentile_rank(objemy, objem) or 0
        sc = _clamp(0.6 * pr + 0.4 * min(100, vazeny * 400))
        top = seg_cpv[0]
        slozky.append({"klic": "pozice", "nazev": "Tržní pozice", "vaha": 25, "skore": round(sc),
                       "vysvetleni": f"Objem větší než u {pr:.0f} % dodavatelů; v hlavním segmentu {top['segment']} "
                                     + (f"{top['poradi']}. z {top['dodavatelu']} dodavatelů" if top['poradi'] else f"mezi {top['dodavatelu']} dodavateli")
                                     + (f" ({_pc(top['podil'])} objemu)." if top['podil'] else ".")})
    # 3 cena
    if med_pomer is not None and trh_med_pomer is not None and len(ceny) >= 2:
        diff = trh_med_pomer - med_pomer
        sc = _clamp(50 + diff * 400)
        slozky.append({"klic": "cena", "nazev": "Cenová konkurenceschopnost", "vaha": 20, "skore": round(sc),
                       "vysvetleni": f"Vítězí v mediánu za {_pc(med_pomer)} předpokládané hodnoty, trh v týchž segmentech za {_pc(trh_med_pomer)} "
                                     f"({len(ceny)} zakázek se skutečnou cenou; rámcové dohody a ceny shodné s odhadem nepočítáme)."})
    # 4 diverzifikace
    if klienti:
        sc = _clamp((1 - (hhi or 1)) * 100 * 0.7 + min(30, len(klienti) * 3))
        slozky.append({"klic": "klienti", "nazev": "Šíře klientské základny", "vaha": 15, "skore": round(sc),
                       "vysvetleni": f"{len(klienti)} zadavatelů; největší tvoří {_pc(shares[0])} objemu." if shares else f"{len(klienti)} zadavatelů."})
    # 5 trend
    if nove or stare:
        ratio = (nove + 1) / (stare + 1)
        sc = _clamp(50 + (ratio - 1) * 50)
        slozky.append({"klic": "trend", "nazev": "Dynamika", "vaha": 15, "skore": round(sc),
                       "vysvetleni": f"{nove} výher za posledních 6 měsíců vs. {stare} v předchozích 6."})
    platne = [s for s in slozky if s["skore"] is not None]
    celk = round(sum(s["skore"] * s["vaha"] for s in platne) / sum(s["vaha"] for s in platne)) if platne else None
    hodnoceni = None if celk is None else ("vysoká" if celk >= 65 else "střední" if celk >= 40 else "nízká")

    # ---- prilezitosti v jejich segmentech ----
    klienti_ico = {k["ico"] for k in klienti}
    prilez = []
    if hlavni_seg:
        for z in con.execute("SELECT * FROM zakazky WHERE lhuta_nabidek >= ? ORDER BY lhuta_nabidek", (today.isoformat(),)):
            z = dict(z)
            if not _is_open(z, today) or cpv_group(z["cpv_hlavni"]) not in hlavni_seg:
                continue
            duvody = [f"segment {cpv_group(z['cpv_hlavni'])}"]
            if z["zadavatel_ico"] in klienti_ico:
                duvody.insert(0, "zadavatel je jejich klient")
            prilez.append({"id": z["id"], "nazev": z["nazev"], "zadavatel": z["zadavatel_nazev"], "hodnota": z["predpokladana_hodnota"],
                           "lhuta": (z["lhuta_nabidek"] or "")[:10], "url": z["url"], "duvody": duvody,
                           "klient": z["zadavatel_ico"] in klienti_ico})
        prilez.sort(key=lambda p: (not p["klient"], -(p["hodnota"] or 0)))

    # ---- seznam zakazek ----
    zak_list = []
    for w in wins:
        zak_list.append({"id": w["id"], "nazev": w["nazev"], "zadavatel": w["zadavatel_nazev"], "datum": w["datum_zahajeni"],
                         "odhad": w["predpokladana_hodnota"], "cena": w["cena_bez_dph"], "vysledek": "výhra",
                         "nabidek": w["pocet_nabidek"], "segment": cpv_group(w["cpv_hlavni"]), "url": w["url"],
                         "overeno_rs": bool(w["overeno_rs"])})
    for u in prohry:
        zak_list.append({"id": u["id"], "nazev": u["nazev"], "zadavatel": u["zadavatel_nazev"], "datum": u["datum_zahajeni"],
                         "odhad": u["predpokladana_hodnota"], "cena": u["nabidkova_cena"], "vysledek": "neúspěch",
                         "nabidek": u["pocet_nabidek"], "segment": cpv_group(u["cpv_hlavni"]), "url": u["url"], "overeno_rs": False})
    zak_list.sort(key=lambda z: z["datum"] or "", reverse=True)

    rs = con.execute("""SELECT COUNT(DISTINCT s.id), SUM(s.hodnota_bez_dph) FROM smlouvy s JOIN smlouvy_strany st ON st.smlouva_id=s.id
                        WHERE st.ico=? AND s.zadavatel_ico != ?""", (ico, ico)).fetchone()
    priznaky = [dict(r) for r in con.execute("SELECT typ, popis FROM priznaky WHERE objekt_id=?", (ico,))]

    return {
        "ico": ico, "nazev": nazev, "ares": firma or None,
        "kpi": {"vyhry": len(win_ids), "ucasti": len(ucast_ids), "ucasti_zname": len(zname), "win_rate": win_rate,
                "objem": objem, "median_cena": _median([w["cena_bez_dph"] for w in wins]),
                "median_pomer": med_pomer, "trh_median_pomer": trh_med_pomer, "klientu": len(klienti),
                "prumer_nabidek": statistics.mean(nab) if nab else None, "jedna_nabidka": jedna, "s_poctem_nabidek": len(nab),
                "smluv_rs": rs[0] or 0, "objem_rs": rs[1] or 0,
                "overeno_rs": sum(1 for w in wins if w["overeno_rs"])},
        "skore": {"celkem": celk, "hodnoceni": hodnoceni, "slozky": slozky},
        "mesice": mesice, "segmenty": segmenty, "klienti": klienti[:12], "ceny": ceny,
        "souboje": souboje, "rivalove": rivalove, "regiony": [{"kraj": k, "pocet": n} for k, n in regiony],
        "prilezitosti": prilez[:20], "zakazky": zak_list[:200], "priznaky": priznaky,
        "zpravy": _zpravy_firmy(con, cfg["zdroje"]["zpravy_base"], nazev if nazev != ico else None, online, cfg.get("exa_api_key")),
    }


# ---------------------------------------------------------------- trh
def trh(con, segment=None):
    zak = [dict(z) for z in con.execute("SELECT id, cpv_hlavni, datum_zahajeni, predpokladana_hodnota, kraj FROM zakazky")]
    if segment:
        zak = [z for z in zak if cpv_group(z["cpv_hlavni"]) == segment]
    ids = {z["id"] for z in zak}
    by_m = Counter(_month(z["datum_zahajeni"]) for z in zak if z["datum_zahajeni"])
    segs = Counter(cpv_group(z["cpv_hlavni"]) for z in con.execute("SELECT cpv_hlavni FROM zakazky"))
    dod = defaultdict(lambda: {"vyhry": 0, "objem": 0.0, "nazev": None})
    for v in con.execute("SELECT zakazka_id, dodavatel_ico, dodavatel_nazev, cena_bez_dph FROM vitezove WHERE dodavatel_ico IS NOT NULL"):
        if v[0] not in ids:
            continue
        d = dod[v[1]]
        d["vyhry"] += 1
        d["objem"] += v[3] or 0
        d["nazev"] = d["nazev"] or v[2]
    nazvy = {r[0]: r[1] for r in con.execute("SELECT ico, nazev FROM dodavatele")}
    tot = sum(d["objem"] for d in dod.values()) or 1
    top = sorted(({"ico": k, "nazev": nazvy.get(k) or v["nazev"], "vyhry": v["vyhry"], "objem": v["objem"], "podil": v["objem"] / tot}
                  for k, v in dod.items()), key=lambda d: (-d["objem"], -d["vyhry"]))[:15]
    return {
        "segment": segment,
        "zakazek": len(zak),
        "hodnota": sum(z["predpokladana_hodnota"] or 0 for z in zak),
        "mesice": [{"mesic": m, "pocet": n} for m, n in sorted(by_m.items())
                   if (date.today() - timedelta(days=730)).isoformat()[:7] <= m <= date.today().isoformat()[:7]],
        "kraje": [{"kraj": k, "pocet": n} for k, n in Counter(z["kraj"] or "neuvedeno" for z in zak).most_common(14)],
        "segmenty": [{"segment": s, "pocet": n} for s, n in segs.most_common(40)],
        "top": top,
    }
