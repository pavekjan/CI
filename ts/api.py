"""Datova vrstva webove aplikace: vyhledani firmy, profil konkurenceschopnosti, prehled trhu.

Vsechno se pocita z lokalni SQLite databaze, kterou plni agenti (Scout/Extractor/Verifier).
ARES a zpravy se pro otevrenou firmu dotahuji zivě (s cache)."""
import bisect
import json
import math
import re
import statistics
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from urllib.parse import quote

from .odkazy import odkazy as _odkazy

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


def odkaz(z):
    """Nejlepsi odkaz na zakazku (NEN, zdroj, Vestnik, nebo hledani na Hlidaci statu)."""
    return _odkazy(z)["url"]


def cpv_group(cpv):
    """Segment = oddil CPV (prvni 2 cislice), napr. '45 Stavební práce'."""
    if not cpv:
        return "neuvedeno"
    return f"{cpv[:2]} {CPV_DIV.get(cpv[:2], 'Ostatní')}"


from .sources.other import ares_firma, google_news
from .util import clean_ico, log, norm, nuts_to_kraj, parse_date, http_get

A = "API"


# ---------------------------------------------------------------- pomocne
def _median(xs):
    xs = [x for x in xs if x is not None]
    return statistics.median(xs) if xs else None


def _pc(x):
    return f"{x * 100:.0f} %"


def _kc(x):
    x = x or 0
    t = f"{x / 1e9:.1f} mld. Kč" if x >= 1e9 else f"{x / 1e6:.1f} mil. Kč" if x >= 1e6 else f"{x / 1e3:.0f} tis. Kč"
    return t.replace(".", ",", 1) if x >= 1e6 else t  # cesky desetinna carka


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
def doplnit_ico_podle_nazvu(con):
    """Cast zaznamu v open datech uvadi dodavatele jen nazvem (bez ICO), napr. "Alza.cz a.s." u nabidky do
    souteze. Kdyz stejny nazev jinde v datech jednoznacne patri jednomu ICO, ICO se doplni.
    Vraci pocet doplnenych radku."""
    mapa = {}
    for tab in ("vitezove", "ucastnici"):
        # bezpecnost: tab je konstanta z kodu (vedome potlaceni nalezu banditu, viz SECURITY.md)
        for ico, nazev in con.execute(f"SELECT DISTINCT dodavatel_ico, dodavatel_nazev FROM {tab} "  # nosec B608
                                      "WHERE dodavatel_ico IS NOT NULL AND dodavatel_nazev IS NOT NULL"):
            mapa.setdefault(norm(nazev), set()).add(ico)
    n = 0
    for tab in ("vitezove", "ucastnici"):
        bez = con.execute(f"SELECT rowid, zakazka_id, dodavatel_nazev FROM {tab} "  # nosec B608
                          "WHERE dodavatel_ico IS NULL AND dodavatel_nazev IS NOT NULL").fetchall()
        for rowid, zid, nazev in bez:
            ica = mapa.get(norm(nazev))
            if not ica or len(ica) != 1:
                continue
            ico = next(iter(ica))
            if con.execute(f"SELECT 1 FROM {tab} WHERE zakazka_id=? AND dodavatel_ico=?", (zid, ico)).fetchone():  # nosec B608
                con.execute(f"DELETE FROM {tab} WHERE rowid=?", (rowid,))  # nosec B608 - duplicitni radek bez ICO
            else:
                con.execute(f"UPDATE OR IGNORE {tab} SET dodavatel_ico=? WHERE rowid=?", (ico, rowid))  # nosec B608
            n += 1
    con.commit()
    return n


_RE_PROLOZENE = re.compile(r"(?:\b\w\b ){3,}\b\w\b(?=\s|$)")


def cisty_nazev(nazev):
    """'S u b t e r r a a.s.' (prolozene pismo z formulare) -> 'Subterra a.s.'"""
    if not nazev:
        return nazev
    return _RE_PROLOZENE.sub(lambda m: m.group(0).replace(" ", ""), nazev).strip()


def sloucit_duplicity(con):
    """Tataz zakazka muze byt v datech dvakrat pod ruznymi cisly (zaznam z Vestniku a zaznam z NEN/profilu
    s jinym Identifikatorem NIPEZ). Za duplicitu se povazuje stejny zadavatel, stejny nazev a stejni vitezove
    se stejnou cenou. Zachova se zaznam z Vestniku, ucastnici se sloucí."""
    kand = con.execute("""SELECT group_concat(id, '|') FROM zakazky WHERE zadavatel_ico IS NOT NULL AND nazev IS NOT NULL
                          GROUP BY zadavatel_ico, nazev HAVING COUNT(*) > 1""").fetchall()
    smazat = []
    for (ids,) in kand:
        skup = defaultdict(list)
        for i in ids.split("|"):
            vit = tuple(sorted((r[0] or "", round(r[1] or 0)) for r in con.execute(
                "SELECT dodavatel_ico, cena_bez_dph FROM vitezove WHERE zakazka_id=?", (i,))))
            if vit and any(c for _, c in vit):
                skup[vit].append(i)
        for stejne in skup.values():
            if len(stejne) < 2:
                continue
            stejne.sort(key=lambda i: (not i.startswith("rvz:Z"), i))
            hlavni = stejne[0]
            for i in stejne[1:]:
                con.execute("""INSERT OR IGNORE INTO ucastnici (zakazka_id, dodavatel_ico, dodavatel_nazev, nabidkova_cena)
                               SELECT ?, dodavatel_ico, dodavatel_nazev, nabidkova_cena FROM ucastnici WHERE zakazka_id=?""", (hlavni, i))
                smazat.append(i)
    for t, sl in (("vitezove", "zakazka_id"), ("ucastnici", "zakazka_id"), ("zakazky", "id")):
        # bezpecnost: t a sl jsou konstanty z kodu, hodnoty jdou jako parametry
        con.executemany(f"DELETE FROM {t} WHERE {sl}=?", [(i,) for i in smazat])  # nosec B608
    con.executemany("DELETE FROM priznaky WHERE objekt_typ='zakazka' AND objekt_id=?", [(i,) for i in smazat])
    con.commit()
    return len(smazat)


def rebuild_index(con):
    """Tabulka `dodavatele` pro rychle vyhledavani (vola se po kazde aktualizaci dat)."""
    sloucene = sloucit_duplicity(con)
    if sloucene:
        log(A, f"Index: sloučeno {sloucene} zakázek zapsaných dvakrát (Věstník + NEN)")
    doplneno = doplnit_ico_podle_nazvu(con)
    if doplneno:
        log(A, f"Index: doplněno IČO podle názvu u {doplneno} dodavatelů")
    con.execute("DELETE FROM dodavatele")
    agg = {}

    def row(ico, nazev):
        r = agg.get(ico)
        if r is None:
            r = agg[ico] = {"nazev": nazev, "vyhry": set(), "ucasti": set(), "objem": 0.0, "smluv": 0, "zname": set()}
        nazev = cisty_nazev(nazev)
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
    # souhrn Registru smluv (36 mesicu): i firmy, ktere v RVZ nic nevyhraly (male zakazky, e-shopy)
    nazvy = dict(con.execute("SELECT ico, nazev FROM subjekty"))
    for ico, n in con.execute("SELECT ico, SUM(pocet) FROM smlouvy_souhrn GROUP BY ico HAVING SUM(pocet) >= 3"):
        r = row(ico, nazvy.get(ico))
        r["smluv"] = max(r["smluv"], n)
    for ico, nazev in con.execute("SELECT ico, nazev FROM firmy"):
        if ico in agg and nazev:
            agg[ico]["nazev"] = nazev
    con.executemany("INSERT INTO dodavatele VALUES (?,?,?,?,?,?,?,?,?)",
                    [(ico, cisty_nazev(r["nazev"]), norm(r["nazev"]), len(r["vyhry"]), len(r["ucasti"]), r["objem"], r["smluv"],
                      len(r["zname"]), len(r["zname"] & r["vyhry"]))
                     for ico, r in agg.items()])
    con.commit()
    log("Indexer", f"index dodavatelu: {len(agg)} firem")
    predpocitat(con)
    log("Indexer", "přehledy trhu předpočítány (rychlé načítání v online verzi)")
    return len(agg)


# ---------------------------------------------------------------- predpocitane prehledy trhu
# Prehledy pres cely trh (vsechny vyhry, vsechny firmy) jsou na velke databazi drahe. Pocitaji se jednou
# po aktualizaci dat (rebuild_index) a ukladaji do tabulky cache, takze je online verze (slaby server)
# jen nacte. Kdyz v cache nejsou (starsi databaze), spocitaji se pri prvnim pouziti.
_PAMET = {}


def _cache_get(con, klic):
    try:
        r = con.execute("SELECT data FROM cache WHERE klic=?", (klic,)).fetchone()
    except Exception:  # starsi databaze bez tabulky cache
        return None
    return json.loads(r[0]) if r else None


def _cache_set(con, klic, data):
    try:
        con.execute("INSERT OR REPLACE INTO cache VALUES (?, ?)", (klic, json.dumps(data, ensure_ascii=False)))
        con.commit()
    except Exception as e:  # jen zrychleni, bez nej vse funguje
        log(A, f"cache {klic}: {str(e)[:80]}")


def _cached(con, klic, fn):
    if klic in _PAMET:
        return _PAMET[klic]
    d = _cache_get(con, klic)
    if d is None:
        d = fn()
        _cache_set(con, klic, d)
    _PAMET[klic] = d
    return d


def smaz_cache(con):
    _PAMET.clear()
    try:
        con.execute("DELETE FROM cache")
        con.commit()
    except Exception:  # nosec B110 - starsi databaze bez tabulky cache
        pass


def _kvantily(xs, n):
    """Zhusteny popis rozdeleni: n bodu (0., 1/(n-1)., ... 100. percentil) ze serazenych hodnot."""
    xs = sorted(x for x in xs if x is not None)
    if not xs:
        return []
    if len(xs) <= n:
        return xs
    return [xs[round(i * (len(xs) - 1) / (n - 1))] for i in range(n)]


def _vazeny_median(rozdeleni):
    """Median sjednoceni nekolika rozdeleni [(kvantily, pocet hodnot)] - kazdy bod vazi pocet/len(kvantily)."""
    body = sorted((q, n / len(qs)) for qs, n in rozdeleni if qs and n for q in qs)
    if not body:
        return None
    pul, acc = sum(w for _, w in body) / 2, 0.0
    for q, w in body:
        acc += w
        if acc >= pul:
            return q
    return body[-1][0]


def _spocti_trh_segmenty(con):
    seg = _segment_stats(con, None)
    out = {}
    for g, s in seg.items():
        top = sorted(s["dod"].items(), key=lambda kv: (-kv[1], -s["dod_n"][kv[0]]))[:40]
        out[g] = {"objem": s["objem"], "vyhry": s["vyhry"], "pomery_n": len(s["pomery"]),
                  "pomery_q": _kvantily(s["pomery"], 101), "objemy": sorted(round(v, 2) for v in s["dod"].values()),
                  "top": [[k, v, s["dod_n"][k]] for k, v in top]}
    rates = [r[0] / r[1] for r in con.execute("SELECT vyhry_zname, ucasti_zname FROM dodavatele WHERE ucasti_zname >= 3")]
    rs_mapa = {r[0]: r[1] or 0 for r in con.execute("SELECT ico, SUM(hodnota) FROM smlouvy_souhrn GROUP BY ico")}
    rvz_mapa = {r[0]: r[1] or 0 for r in con.execute("SELECT ico, objem FROM dodavatele WHERE objem > 0")}
    vsechny = [rvz_mapa.get(k, 0) + rs_mapa.get(k, 0) for k in set(rs_mapa) | set(rvz_mapa)]
    return {"seg": out, "trh_wr": _median(rates) or 0.3, "verejne_q": _kvantily(vsechny, 1001)}


def trh_segmenty(con):
    return _cached(con, "trh_segmenty", lambda: _spocti_trh_segmenty(con))


def _nazvy(con, icos):
    """Nazvy jen pro potrebne firmy (ne cela tabulka dodavatelu)."""
    icos = [i for i in set(icos) if i]
    out = {}
    for i in range(0, len(icos), 500):
        kus = icos[i:i + 500]
        # bezpecnost: v dotazu jsou jen otazniky, hodnoty jdou jako parametry
        out.update(dict(con.execute(f"SELECT ico, nazev FROM dodavatele WHERE ico IN ({','.join('?' * len(kus))})", kus)))  # nosec B608
    return out


def predpocitat(con):
    """Po aktualizaci dat: smazat a znovu spocitat prehledy trhu (volano z rebuild_index)."""
    smaz_cache(con)
    trh_segmenty(con)
    _trh_vse(con)
    stav(con)


# ---------------------------------------------------------------- stav dat
def rozsah_dat(con):
    """Obdobi, ktere data pokryvaji. Nekolik zakazek ma datum zahajeni o roky drive (dlouhe ramcove smlouvy,
    preklepy), proto se zacatek bere jako 5. percentil, ne minimum. Konec nesmi byt v budoucnosti."""
    pl = "datum_zahajeni >= '2000' AND datum_zahajeni <= date('now', '+1 day')"
    n = con.execute(f"SELECT COUNT(*) FROM zakazky WHERE {pl}").fetchone()[0]  # nosec B608 - pl je konstanta
    if not n:
        return (None, None)
    od = con.execute(f"SELECT datum_zahajeni FROM zakazky WHERE {pl} ORDER BY datum_zahajeni LIMIT 1 OFFSET ?",  # nosec B608
                     (n // 20,)).fetchone()[0]
    do = con.execute(f"SELECT MAX(datum_zahajeni) FROM zakazky WHERE {pl}").fetchone()[0]  # nosec B608
    return (od, do)


def obdobi(con):
    """Za jake obdobi data jsou: RVZ = zpracovane mesicni soubory, Registr smluv = zpracovane mesice registru."""
    rvz = sorted(f"{k[-4:]}-{k[-7:-5]}" for (k,) in con.execute(
        "SELECT DISTINCT substr(klic, 5, instr(substr(klic, 5), '.zip') - 1) FROM soubory WHERE klic LIKE 'rvz:rvz_VZ-%'"))
    rs = sorted({k[4:8] + "-" + k[9:11] for (k,) in con.execute("SELECT klic FROM soubory WHERE klic LIKE 'rs3:%'")})
    return {"rvz_od": rvz[0] if rvz else None, "rvz_do": rvz[-1] if rvz else None, "rvz_mesicu": len(rvz),
            "rs_od": rs[0] if rs else None, "rs_do": rs[-1] if rs else None, "rs_mesicu": len(rs)}


def rs_firmy(con, ico, mesicu=36):
    """Registr smluv pro jednu firmu ze souhrnu: pocet a objem smluv, po mesicich a podle odberatelu."""
    mes = con.execute("SELECT mesic, SUM(pocet), SUM(hodnota) FROM smlouvy_souhrn WHERE ico=? GROUP BY mesic ORDER BY mesic",
                      (ico,)).fetchall()
    if not mes:
        return None
    odb = con.execute("""SELECT o.zadavatel_ico, COALESCE(MAX(s.nazev), o.zadavatel_ico), SUM(o.pocet), SUM(o.hodnota)
                         FROM smlouvy_odberatele o LEFT JOIN subjekty s ON s.ico=o.zadavatel_ico WHERE o.ico=?
                         GROUP BY o.zadavatel_ico ORDER BY SUM(o.hodnota) DESC LIMIT 12""", (ico,)).fetchall()
    od = (date.today().replace(day=1) - timedelta(days=31 * mesicu)).isoformat()[:7]
    return {"pocet": sum(r[1] for r in mes), "objem": sum(r[2] or 0 for r in mes),
            "zadavatelu": con.execute("SELECT COUNT(DISTINCT zadavatel_ico) FROM smlouvy_odberatele WHERE ico=?", (ico,)).fetchone()[0],
            "mesice": [{"mesic": m, "pocet": n, "objem": h or 0} for m, n, h in mes if m >= od],
            "odberatele": [{"ico": i, "nazev": n, "pocet": c, "objem": h or 0} for i, n, c, h in odb]}


_HLIDAC_CACHE = {}


def hlidac_smlouvy(cfg, ico, online=True):
    """Pro srovnani: kolik smluv (Registr smluv) a kolik verejnych zakazek (jako dodavatel) ma firma za celou
    historii podle Hlidace statu (token zdarma). Hlidac pocita i zakazky z profilu zadavatelu a od roku 2016,
    proto jsou jeho cisla vyssi. Odkazy funguji i bez tokenu. Vysledek se drzi 24 h v pameti."""
    url = f"https://www.hlidacstatu.cz/hledat?Q=ico%3A{ico}"
    vz_url = f"https://www.hlidacstatu.cz/verejnezakazky/hledat?Q=icododavatel%3A{ico}"
    out = {"url": url, "pocet": None, "zakazky_url": vz_url, "zakazky": None}
    token = cfg.get("hlidac_token")
    if not token or not online:
        return out
    hit = _HLIDAC_CACHE.get(ico)
    if hit and hit[0] > datetime.now() - timedelta(hours=24):
        return hit[1]
    for pole, cesta, dotaz in (("pocet", "smlouvy/hledat", f"ico:{ico}"),
                               ("zakazky", "verejnezakazky/hledat", f"icododavatel:{ico}")):
        try:
            r = http_get(cfg["zdroje"]["hlidac_base"] + cesta, params={"dotaz": dotaz, "strana": 1},
                         headers={"Authorization": f"Token {token}"}, timeout=10, retries=1)
            if r.status_code == 200:
                d = r.json()
                n = d.get("total", d.get("Total"))
                out[pole] = int(n) if isinstance(n, (int, float)) else None
        except Exception as e:  # doplnek: pri chybe profil funguje dal
            log(A, f"Hlidac statu {ico} ({cesta}): {str(e)[:120]}")
    if len(_HLIDAC_CACHE) > 2000:
        _HLIDAC_CACHE.clear()
    _HLIDAC_CACHE[ico] = (datetime.now(), out)
    return out


def _spocti_stav(con):
    one = lambda q: con.execute(q).fetchone()[0]  # noqa: E731
    rng = rozsah_dat(con)
    return {
        "zakazek": one("SELECT COUNT(*) FROM zakazky"),
        "vitezu": one("SELECT COUNT(*) FROM vitezove"),
        "dodavatelu": one("SELECT COUNT(*) FROM dodavatele"),
        "smluv": max(one("SELECT COUNT(*) FROM smlouvy"), one("SELECT COALESCE(SUM(pocet), 0) FROM smlouvy_souhrn")),
        "obdobi": obdobi(con),
        "od": rng[0], "do": rng[1],
    }


def stav(con, demo=False):
    last = con.execute("SELECT konec FROM behy WHERE stav='ok' ORDER BY id DESC LIMIT 1").fetchone()
    # prazdna databaze (behem prvniho stahovani) se do cache neuklada, aby se cisla po nacteni dat obnovila
    zaklad = _cached(con, "stav2", lambda: _spocti_stav(con)) if not demo else _spocti_stav(con)
    if not zaklad["zakazek"]:
        _PAMET.pop("stav2", None)
        try:
            con.execute("DELETE FROM cache WHERE klic='stav2'")
        except Exception:  # nosec B110
            pass
    return {"demo": demo, **zaklad,
            "firem_ares": con.execute("SELECT COUNT(*) FROM firmy").fetchone()[0],
            "posledni_aktualizace": last[0] if last else None}


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
    rows = con.execute(f"SELECT * FROM dodavatele WHERE {where} ORDER BY objem DESC, smluv_rs DESC, vyhry DESC LIMIT ?",  # nosec B608
                       [f"%{w}%" for w in words] + [limit]).fetchall()
    out = [dict(r) for r in rows]
    if len(out) < 3 and ares_base:
        for f in ares_hledat(ares_base, q):
            if not any(o["ico"] == f["ico"] for o in out):
                out.append({"ico": f["ico"], "nazev": f["nazev"], "vyhry": 0, "ucasti": 0, "objem": 0, "smluv_rs": 0, "jen_ares": True})
    return out[:limit]


def ares_hledat(base, nazev, pocet=5, ico=None):
    """ARES vyhledani podle nazvu (nebo IČO): POST .../ekonomicke-subjekty/vyhledat (nejlepsi snaha, pri chybe prazdno)."""
    try:
        from .util import session
        telo = {"ico": [ico]} if ico else {"obchodniJmeno": nazev}
        r = session().post(base + "vyhledat", json={**telo, "pocet": pocet, "start": 0},
                           headers={"Accept": "application/json"}, timeout=10)
        if r.status_code != 200:
            return []
        return [{"ico": s.get("ico"), "nazev": s.get("obchodniJmeno"), "sidlo": (s.get("sidlo") or {}).get("textovaAdresa")}
                for s in r.json().get("ekonomickeSubjekty", [])]
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
        # nejdriv zpravy za posledni rok (Google jinak radi podle relevance a vraci i 10 let stare clanky)
        items = google_news(base, f"{q} when:1y", limit=30, retries=1) or google_news(base, q, limit=30, retries=1)
        for it in items:
            it["dotaz"] = q
        items = sorted(items, key=lambda it: it.get("datum") or "", reverse=True)[:8]
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


def _konec_dat(con):
    """Posledni den, za ktery maji data zakazky (ne budouci terminy z preklepu)."""
    d = con.execute("SELECT MAX(datum_zahajeni) FROM zakazky WHERE datum_zahajeni <= ?", (date.today().isoformat(),)).fetchone()[0]
    try:
        return date.fromisoformat(d[:10]) if d else date.today()
    except ValueError:
        return date.today()


def _trh_dynamika(con, ref):
    """Kolik vyher a smluv mel cely trh v poslednich 6 mesicich dat a v 6 mesicich predtim (pro srovnani firmy s trhem)."""
    t6, t12 = (ref - timedelta(days=183)).isoformat(), (ref - timedelta(days=366)).isoformat()
    a, b = con.execute("""SELECT SUM(z.datum_zahajeni >= ? AND z.datum_zahajeni <= ?), SUM(z.datum_zahajeni >= ? AND z.datum_zahajeni < ?)
                          FROM vitezove v JOIN zakazky z ON z.id=v.zakazka_id WHERE z.datum_zahajeni >= ?""",
                       (t6, ref.isoformat(), t12, t6, t12)).fetchone()
    m6, m12, m0 = t6[:7], t12[:7], ref.isoformat()[:7]
    ra, rb = con.execute("""SELECT SUM(CASE WHEN mesic >= ? AND mesic < ? THEN pocet ELSE 0 END),
                                   SUM(CASE WHEN mesic >= ? AND mesic < ? THEN pocet ELSE 0 END)
                            FROM smlouvy_souhrn WHERE mesic >= ? AND mesic < ?""", (m6, m0, m12, m6, m12, m0)).fetchone()
    return {"vyhry_nove": a or 0, "vyhry_stare": b or 0, "rs_nove": ra or 0, "rs_stare": rb or 0}


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
    ts_ = trh_segmenty(con)
    prazdny = {"objem": 0, "vyhry": 0, "pomery_n": 0, "pomery_q": [], "objemy": [], "top": []}
    seg_all = defaultdict(lambda: prazdny, ts_["seg"])
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
        sa = seg_all[g]
        tot = sa["objem"] or 0
        objemy = sa["objemy"]  # objemy vsech dodavatelu v segmentu, vzestupne
        poradi = (1 + len(objemy) - bisect.bisect_right(objemy, round(s["objem"], 2))) if g != NEUVEDENO and objemy else None
        segmenty.append({"segment": g, "vyhry": s["vyhry"], "objem": s["objem"],
                         "podil": (s["objem"] / tot) if tot and g != NEUVEDENO else None, "poradi": poradi,
                         "dodavatelu": len(objemy),
                         "median_pomer": _median(s["pomery"]), "trh_median_pomer": _vazeny_median([(sa["pomery_q"], sa["pomery_n"])]),
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
    trh_med_pomer = _vazeny_median([(seg_all[g]["pomery_q"], seg_all[g]["pomery_n"]) for g in seg_f if g != NEUVEDENO])

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
    riv = defaultdict(float)
    riv_n = Counter()
    for g in hlavni_seg:
        for k, v, n in seg_all[g]["top"]:
            if k != ico:
                riv[k] += v
                riv_n[k] += n
    nazvy = _nazvy(con, list(h2h) + list(riv))
    souboje = sorted(({"ico": k, "nazev": nazvy.get(k) or v["nazev"] or k, **{x: v[x] for x in ("stretu", "my_vyhra", "oni_vyhra")}}
                      for k, v in h2h.items()), key=lambda s: (-s["stretu"], -s["oni_vyhra"]))[:15]
    # rivalove v segmentech (i bez dat o ucastnicich): nejvetsi dodavatele hlavnich segmentu
    rivalove = [{"ico": k, "nazev": nazvy.get(k) or k, "objem": v, "vyhry": riv_n[k]}
                for k, v in sorted(riv.items(), key=lambda kv: (-kv[1], -riv_n[kv[0]]))
                if k and re.fullmatch(r"\d{8}", str(k))][:10]

    # ---- regiony ----
    regiony = Counter(nuts_to_kraj(w["kraj"]) if (w["kraj"] or "").upper().startswith("CZ") else (w["kraj"] or "neuvedeno")
                      for w in wins).most_common()

    # ---- konkurencni intenzita ----
    nab = [w["pocet_nabidek"] for w in wins if w["pocet_nabidek"]]
    jedna = sum(1 for n in nab if n == 1)

    # ---- trend: poslednich 6 mesicu vs predchozich 6 ----
    # Okna se pocitaji od konce dat, ne od dneska. U nejcerstvejsich soutezi jeste neni znam vitez, takze vyher
    # v poslednich mesicich je v datech vzdy mene - firma se proto porovnava s celym trhem ve stejnych oknech.
    ref = min(today, _konec_dat(con))
    t6 = (ref - timedelta(days=183)).isoformat()
    t12 = (ref - timedelta(days=366)).isoformat()
    nove = sum(1 for w in wins if t6 <= (w["datum_zahajeni"] or "") <= ref.isoformat())
    stare = sum(1 for w in wins if t12 <= (w["datum_zahajeni"] or "") < t6)
    trh_dyn = _cached(con, f"dynamika:{ref.isoformat()}", lambda: _trh_dynamika(con, ref))

    # ---- skore konkurenceschopnosti ----
    rs_souhrn = rs_firmy(con, ico)
    slozky = []
    # 1 uspesnost v soutezich (RVZ). Pri malem vzorku se win rate "smrsti" k medianu trhu (Bayesuv odhad
    #   s K virtualnimi soutezemi), aby 0 ze 3 neznamenalo 0 bodu.
    K_SHRINK = 5
    if win_rate is not None and len(zname) >= 1:
        # trzni srovnani jen z firem, u kterych zdroj uvadi ucastniky (jinak by win rate byl umele 100 %)
        trh_wr = ts_["trh_wr"]
        n_z, v_z = len(zname), len(win_ids & zname)
        wr_adj = (v_z + K_SHRINK * trh_wr) / (n_z + K_SHRINK)
        sc = _clamp(50 + (wr_adj - trh_wr) * 150)
        malo = n_z < 5
        slozky.append({"klic": "uspesnost", "nazev": "Úspěšnost v soutěžích", "vaha": 25, "skore": round(sc), "malo_dat": malo,
                       "vysvetleni": f"Vyhrála {_pc(win_rate)} soutěží, kterých se účastnila ({v_z} z {n_z}, kde zdroj uvádí všechny účastníky); "
                                     f"běžná firma na trhu vyhraje {_pc(trh_wr)}."
                                     + (f" Málo dat: odhad je přitažený k mediánu trhu (jako by firma měla navíc {K_SHRINK} "
                                        f"průměrných soutěží), upravený win rate {_pc(wr_adj)}." if malo else "")})
    elif ucast_ids:
        slozky.append({"klic": "uspesnost", "nazev": "Úspěšnost v soutěžích", "vaha": 25, "skore": None,
                       "vysvetleni": "Data o neúspěšných nabídkách chybějí (u části zakázek je zdroj neuvádí) – nelze spočítat."})
    # 2 trzni pozice: objem verejnych trzeb = vyhry v RVZ + smlouvy v Registru smluv (i male zakazky a e-shopy)
    rs_objem = (rs_souhrn or {}).get("objem", 0) or 0
    verejne = objem + rs_objem
    if verejne > 0:
        q = ts_["verejne_q"]  # rozdeleni verejnych trzeb vsech firem (kvantily)
        pr = (100.0 * bisect.bisect_right(q, verejne) / len(q)) if q else 0
        seg_cpv = [s for s in segmenty if s["segment"] != NEUVEDENO]
        top = seg_cpv[0] if seg_cpv else None
        # poradi v hlavnim segmentu: 1. ze 100 -> 100 bodu, prostredni -> 50
        por = (100 * (1 - (top["poradi"] - 1) / max(1, top["dodavatelu"]))) if (top and top["poradi"]) else None
        sc = _clamp(0.7 * pr + 0.3 * por) if por is not None else _clamp(pr)
        slozky.append({"klic": "pozice", "nazev": "Tržní pozice", "vaha": 25, "skore": round(sc),
                       "vysvetleni": f"Veřejné tržby {_kc(verejne)} (soutěže {_kc(objem)} + Registr smluv {_kc(rs_objem)}) "
                                     + (f"patří mezi 1 % největších dodavatelů." if pr >= 99 else f"jsou vyšší než u {pr:.0f} % dodavatelů.")
                                     + ((f" V hlavním oboru {top['segment'].split(' ', 1)[-1].lower()} " + (f"{top['poradi']}. z {top['dodavatelu']} dodavatelů." if top['poradi'] else f"mezi {top['dodavatelu']} dodavateli."))
                                        if top else "")})
    # 3 cena
    # z 2-3 zakazek se o cenach nic spolehliveho rict neda (Makro: 2 z 891) -> slozka az od 5 zakazek
    if med_pomer is not None and trh_med_pomer is not None and len(ceny) >= 5:
        diff = trh_med_pomer - med_pomer
        sc = _clamp(50 + diff * 400)
        n_c = len(ceny)
        slozky.append({"klic": "cena", "nazev": "Cenová konkurenceschopnost", "vaha": 20, "skore": round(sc), "malo_dat": n_c < 10,
                       "vysvetleni": f"Vítězí v mediánu za {_pc(med_pomer)} předpokládané hodnoty, trh v týchž oborech za {_pc(trh_med_pomer)} "
                                     f"(spočteno z {n_c} {'zakázky' if n_c == 1 else 'zakázek'} se skutečnou cenou; rámcové dohody "
                                     f"a ceny shodné s odhadem nepočítáme)." + (" Málo dat, berte orientačně." if n_c < 10 else "")})
    elif ceny:
        slozky.append({"klic": "cena", "nazev": "Cenová konkurenceschopnost", "vaha": 20, "skore": None,
                       "vysvetleni": f"Jen {len(ceny)} {'zakázka' if len(ceny) == 1 else 'zakázky' if len(ceny) < 5 else 'zakázek'} se známou "
                                     f"předpokládanou i skutečnou cenou – na spolehlivé srovnání je potřeba aspoň 5."})
    # 4 sire klientske zakladny: zadavatele z vyher v RVZ i odberatele z Registru smluv
    obj_k = defaultdict(float)
    for k in klienti:
        obj_k[k["ico"]] += k["objem"] or 0
    for r in con.execute("SELECT zadavatel_ico, SUM(hodnota) FROM smlouvy_odberatele WHERE ico=? GROUP BY zadavatel_ico", (ico,)):
        if r[0]:
            obj_k[r[0]] += r[1] or 0
    if obj_k:
        tot_k = sum(obj_k.values())
        hhi_k = sum((v / tot_k) ** 2 for v in obj_k.values()) if tot_k else 1
        sc = _clamp((1 - hhi_k) * 60 + min(40, 40 * math.log10(1 + len(obj_k)) / 2))   # 100 zakazniku -> plnych 40 bodu
        nejv = max(obj_k.values()) / tot_k if tot_k else None
        slozky.append({"klic": "klienti", "nazev": "Šíře klientské základny", "vaha": 15, "skore": round(sc),
                       "vysvetleni": f"{len(obj_k)} veřejných zákazníků (soutěže + Registr smluv)"
                                     + (f"; největší tvoří {_pc(nejv)} objemu." if nejv is not None else ".")})
    # samostatne KPI: podil na trhu v hlavnim oboru (vyhrane soutezni objemy) a zavislost na nejvetsim zakaznikovi
    seg_hl = next((x for x in segmenty if x["segment"] != NEUVEDENO and x["podil"] is not None), None)
    podil_trhu = ({"obor": seg_hl["segment"].split(" ", 1)[-1], "podil": seg_hl["podil"], "poradi": seg_hl["poradi"],
                   "dodavatelu": seg_hl["dodavatelu"]} if seg_hl else None)
    nejvetsi_zakaznik = None
    if obj_k and sum(obj_k.values()) > 0:
        tot_z = sum(obj_k.values())
        kl_ico, kl_obj = max(obj_k.items(), key=lambda kv: kv[1])
        jm = next((k["nazev"] for k in klienti if k["ico"] == kl_ico), None)
        if not jm:
            r = con.execute("SELECT nazev FROM subjekty WHERE ico=?", (kl_ico,)).fetchone()
            jm = (r[0] if r else None) or kl_ico
        nejvetsi_zakaznik = {"nazev": jm, "podil": kl_obj / tot_z, "zakazniku": len(obj_k)}
    # 5 dynamika: vyhry 6 v 6 mesicu, a kdyz Registr smluv pokryva aspon 12 mesicu, i pocet smluv
    rs_mes = {m["mesic"]: m["pocet"] for m in (rs_souhrn or {}).get("mesice", [])}
    m6, m12, m0 = t6[:7], t12[:7], ref.isoformat()[:7]
    rs_nove = sum(n for m, n in rs_mes.items() if m6 <= m < m0)  # rozbehnuty mesic se nepocita
    rs_stare = sum(n for m, n in rs_mes.items() if m12 <= m < m6)
    rs_pokryti = len({m for m in rs_mes if m >= m12}) >= 10
    if nove or stare or (rs_pokryti and (rs_nove or rs_stare)):
        a, b_ = nove + (rs_nove if rs_pokryti else 0), stare + (rs_stare if rs_pokryti else 0)
        ta = trh_dyn["vyhry_nove"] + (trh_dyn["rs_nove"] if rs_pokryti else 0)
        tb = trh_dyn["vyhry_stare"] + (trh_dyn["rs_stare"] if rs_pokryti else 0)
        trh_ratio = (ta / tb) if ta and tb else 1.0
        ratio = ((a + 1) / (b_ + 1)) / trh_ratio  # firma vuci trhu: 1 = roste stejne jako trh
        sc = _clamp(50 + math.log2(ratio) * 25)
        slozky.append({"klic": "trend", "nazev": "Dynamika", "vaha": 15, "skore": round(sc),
                       "vysvetleni": f"{nove} výher za posledních 6 měsíců dat vs. {stare} v předchozích 6"
                                     + (f"; smlouvy v Registru {rs_nove} vs. {rs_stare}" if rs_pokryti else
                                        " (Registr smluv zatím nepokrývá celý rok, do dynamiky se nepočítá)")
                                     + f". Porovnáno s celým trhem, kterému se ve stejných obdobích změnil počet o "
                                       f"{(trh_ratio - 1) * 100:+.0f} % (u nejnovějších soutěží často ještě není znám vítěz)."})
    platne = [s for s in slozky if s["skore"] is not None]
    celk = round(sum(s["skore"] * s["vaha"] for s in platne) / sum(s["vaha"] for s in platne)) if platne else None
    hodnoceni = None if celk is None else ("vysoká" if celk >= 65 else "střední" if celk >= 40 else "nízká")
    malo_dat = sum(1 for s_ in platne) < 3 or any(s_.get("malo_dat") for s_ in platne)

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
                           "lhuta": (z["lhuta_nabidek"] or "")[:10], "url": odkaz(z), "duvody": duvody,
                           "klient": z["zadavatel_ico"] in klienti_ico})
        prilez.sort(key=lambda p: (not p["klient"], -(p["hodnota"] or 0)))

    # ---- seznam zakazek ----
    zak_list = []
    for w in wins:
        zak_list.append({"id": w["id"], "nazev": w["nazev"], "zadavatel": w["zadavatel_nazev"], "datum": w["datum_zahajeni"],
                         "odhad": w["predpokladana_hodnota"], "cena": w["cena_bez_dph"], "vysledek": "výhra",
                         "nabidek": w["pocet_nabidek"], "segment": cpv_group(w["cpv_hlavni"]), "url": odkaz(w),
                         "overeno_rs": bool(w["overeno_rs"])})
    for u in prohry:
        zak_list.append({"id": u["id"], "nazev": u["nazev"], "zadavatel": u["zadavatel_nazev"], "datum": u["datum_zahajeni"],
                         "odhad": u["predpokladana_hodnota"], "cena": u["nabidkova_cena"], "vysledek": "neúspěch",
                         "nabidek": u["pocet_nabidek"], "segment": cpv_group(u["cpv_hlavni"]), "url": odkaz(u), "overeno_rs": False})
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
                "smluv_rs_souhrn": (rs_souhrn or {}).get("pocet", 0), "objem_rs_souhrn": (rs_souhrn or {}).get("objem", 0),
                "overeno_rs": sum(1 for w in wins if w["overeno_rs"]),
                "podil_trhu": podil_trhu, "nejvetsi_zakaznik": nejvetsi_zakaznik},
        "skore": {"celkem": celk, "hodnoceni": hodnoceni, "slozky": slozky, "malo_dat": malo_dat},
        "mesice": mesice, "segmenty": segmenty, "klienti": klienti[:12], "ceny": ceny,
        "souboje": souboje, "rivalove": rivalove, "regiony": [{"kraj": k, "pocet": n} for k, n in regiony],
        "prilezitosti": prilez[:20], "zakazky": zak_list[:200], "priznaky": priznaky,
        "registr": rs_souhrn, "obdobi": obdobi(con), "hlidac": hlidac_smlouvy(cfg, ico, online),
        "zpravy": _zpravy_firmy(con, cfg["zdroje"]["zpravy_base"], nazev if nazev != ico else None, online, cfg.get("exa_api_key")),
    }


# ---------------------------------------------------------------- trh
def _trh_vse(con):
    """Prehled trhu celkem i pro kazdy segment najednou (jeden pruchod daty), ulozeny v cache."""
    if _cache_get(con, "trh:") is not None:
        return None
    dnes = date.today()
    od_m, do_m = (dnes - timedelta(days=730)).isoformat()[:7], dnes.isoformat()[:7]
    agg = defaultdict(lambda: {"zakazek": 0, "hodnota": 0.0, "mesice": Counter(), "kraje": Counter(), "odhad": 0,
                               "dod": defaultdict(lambda: {"vyhry": 0, "objem": 0.0, "nazev": None})})
    seg_z = {}
    segs, odhad = Counter(), Counter()
    for zid, c, d, h, kraj in con.execute("SELECT id, cpv_hlavni, datum_zahajeni, predpokladana_hodnota, kraj FROM zakazky"):
        g = cpv_group(c)
        seg_z[zid] = g
        segs[g] += 1
        je_odhad = bool(c and len(c) == 2)  # segment odhadnuty z nazvu zakazky (ts/segmenty.py), ne uvedene CPV
        if je_odhad:
            odhad[g] += 1
        for k in ("", g):
            a_ = agg[k]
            a_["zakazek"] += 1
            a_["hodnota"] += h or 0
            if d and od_m <= d[:7] <= do_m:
                a_["mesice"][d[:7]] += 1
            a_["kraje"][kraj or "neuvedeno"] += 1
            a_["odhad"] += je_odhad
    for zid, ico, nazev, cena in con.execute(
            "SELECT zakazka_id, dodavatel_ico, dodavatel_nazev, cena_bez_dph FROM vitezove WHERE dodavatel_ico IS NOT NULL"):
        g = seg_z.get(zid)
        if g is None:
            continue
        for k in ("", g):
            dd = agg[k]["dod"][ico]
            dd["vyhry"] += 1
            dd["objem"] += cena or 0
            dd["nazev"] = dd["nazev"] or nazev
    del seg_z
    segmenty_ = [{"segment": s_, "pocet": n, "odhad": odhad[s_]} for s_, n in segs.most_common(40)]
    tops = {k: sorted(a_["dod"].items(), key=lambda kv: (-kv[1]["objem"], -kv[1]["vyhry"]))[:15] for k, a_ in agg.items()}
    nazvy = _nazvy(con, [i for t in tops.values() for i, _ in t])
    vysl = {}
    for k, a_ in agg.items():
        tot = sum(d["objem"] for d in a_["dod"].values()) or 1
        vysl["trh:" + k] = {
            "segment": k or None, "zakazek": a_["zakazek"], "hodnota": a_["hodnota"],
            "mesice": [{"mesic": m, "pocet": n} for m, n in sorted(a_["mesice"].items())],
            "kraje": [{"kraj": kr, "pocet": n} for kr, n in a_["kraje"].most_common(14)],
            "segmenty": segmenty_, "odhadnuto": a_["odhad"],
            "top": [{"ico": i, "nazev": nazvy.get(i) or v["nazev"], "vyhry": v["vyhry"], "objem": v["objem"],
                     "podil": v["objem"] / tot} for i, v in tops[k]]}
    for k, v in vysl.items():
        _cache_set(con, k, v)
    return vysl


def trh(con, segment=None):
    klic = "trh:" + (segment or "")
    if klic in _PAMET:
        return _PAMET[klic]
    d = _cache_get(con, klic)
    if d is None:
        vse = _trh_vse(con) or {}
        d = vse.get(klic) or _cache_get(con, klic)
    if d is None:  # segment bez zakazek
        d = {"segment": segment, "zakazek": 0, "hodnota": 0, "mesice": [], "kraje": [], "segmenty": [],
             "odhadnuto": 0, "top": []}
    if len(_PAMET) < 200:
        _PAMET[klic] = d
    return d


# ---------------------------------------------------------------- knowledge graph
def graf(con, ico, cfg):
    """Knowledge graph firmy pro zobrazeni v aplikaci (obdoba exportu do Obsidianu):
    firma -> zakaznici (RVZ i Registr smluv), konkurenti, obory (CPV), vyhrane zakazky a zdroje dat.
    Kazdy uzel nese odkaz: firma/segment uvnitr aplikace, zakazka a zdroj ven."""
    p = profil(con, ico, cfg, online=False)
    uzly, hrany, ids = [], [], set()

    def uzel(uid, typ, nazev, odkaz=None, vaha=1.0, info=None):
        if uid not in ids:
            ids.add(uid)
            uzly.append({"id": uid, "typ": typ, "nazev": (nazev or uid)[:90], "odkaz": odkaz, "vaha": vaha, "info": info})
        return uid

    def hrana(a, b, typ, popis=None):
        hrany.append({"od": a, "do": b, "typ": typ, "popis": popis})

    f = uzel(f"f:{p['ico']}", "firma", p["nazev"], f"#/firma/{p['ico']}", 3)
    for s in p["segmenty"][:6]:
        if s["segment"] == NEUVEDENO:
            continue
        hrana(f, uzel(f"s:{s['segment']}", "obor", s["segment"], f"#/trh/{quote(s['segment'])}", 1.6), "pusobi_v",
              f"{s['vyhry']}× výhra")
    for k in p["klienti"][:8]:
        hrana(f, uzel(f"z:{k['ico']}", "zadavatel", k["nazev"], f"https://ares.gov.cz/ekonomicke-subjekty?ico={k['ico']}", 1.3,
                      f"{k['vyhry']}× výhra v soutěži"), "zakaznik", "RVZ")
    for o in ((p.get("registr") or {}).get("odberatele") or [])[:8]:
        hrana(f, uzel(f"z:{o['ico']}", "zadavatel", o["nazev"], f"https://ares.gov.cz/ekonomicke-subjekty?ico={o['ico']}", 1.3,
                      f"{o['pocet']} smluv"), "zakaznik", "Registr smluv")
    for r in p["rivalove"][:6]:
        hrana(f, uzel(f"f:{r['ico']}", "konkurent", r["nazev"], f"#/firma/{r['ico']}", 1.4), "konkurent", "stejné obory")
    for s in p["souboje"][:4]:
        hrana(f, uzel(f"f:{s['ico']}", "konkurent", s["nazev"], f"#/firma/{s['ico']}", 1.4), "souboj", f"{s['stretu']}× střet")
    for z in [z for z in p["zakazky"] if z["vysledek"] != "neúspěch"][:10]:
        zid = uzel(f"t:{z['id']}", "zakazka", z["nazev"], z["url"], 0.9, z.get("datum"))
        hrana(f, zid, "vyhral", "výhra")
        if z["segment"] != NEUVEDENO and f"s:{z['segment']}" in ids:
            hrana(zid, f"s:{z['segment']}", "obor")
    zdroje = [("ARES", f"https://ares.gov.cz/ekonomicke-subjekty?ico={p['ico']}"),
              ("Hlídač státu", (p.get("hlidac") or {}).get("url")),
              ("Věstník / NEN (RVZ)", "https://isvz.nipez.cz/")]
    for nazev, url in zdroje:
        if url:
            hrana(f, uzel(f"d:{nazev}", "zdroj", nazev, url, 0.8), "zdroj")
    return {"ico": p["ico"], "nazev": p["nazev"], "uzly": uzly, "hrany": hrany}
