"""Agent ANALYST - odpovida na KIQ 1-5: prehled trhu, profily konkurentu, win rate,
cenove benchmarky, typicke podminky, prilezitosti a nase pozice. Navic bid/no-bid skore."""
import csv
import os
import statistics
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta

from .util import OUT_DIR, log, norm, parse_date
from .bezpecnost import bunka_csv

A = "Analyst"

CPV_SKUPINY = {
    "72": "IT služby (vývoj, poradenství, podpora)", "48": "Software a informační systémy", "302": "Počítače a kancelářská technika",
    "322": "Telekomunikační zařízení", "323": "Rozhlas/TV/AV technika", "503": "Opravy a údržba IT", "642": "Telekomunikační služby",
    "793": "Průzkum trhu a služby", "451": "Příprava staveniště", "452": "Stavební práce – budovy a inženýrské stavby",
    "453": "Stavební instalace", "454": "Dokončovací stavební práce", "455": "Pronájem stavebních strojů",
    "712": "Architektonické služby", "713": "Inženýrské služby", "712/713": "Projekce a dozor", "442": "Stavební konstrukce",
    "441": "Stavební materiály", "45": "Stavební práce", "71": "Architektonické a inženýrské služby",
}


def cpv_group(cpv):
    if not cpv:
        return "neuvedeno"
    g = cpv[:3]
    return f"{g} – {CPV_SKUPINY.get(g, CPV_SKUPINY.get(cpv[:2], 'ostatní'))}"


def _median(xs):
    xs = [x for x in xs if x is not None]
    return statistics.median(xs) if xs else None


def _pct(xs, q):
    xs = sorted(x for x in xs if x is not None)
    if not xs:
        return None
    k = (len(xs) - 1) * q
    f = int(k)
    c = min(f + 1, len(xs) - 1)
    return xs[f] + (xs[c] - xs[f]) * (k - f)


def _is_open(z, today):
    st = norm(z["stav"])
    if any(w in st for w in ("zrus", "zadan", "ukoncen", "dokoncen", "uzavren")):
        return False
    d = parse_date(z["lhuta_nabidek"])
    return bool(d and d >= today)


def _is_cancelled(z):
    return "zrus" in norm(z["stav"])


CSV_PREFIX = ""


def _write_csv(name, rows, header, prefix=None):
    prefix = CSV_PREFIX if prefix is None else prefix
    path = os.path.join(OUT_DIR, prefix + name)
    with open(path, "w", newline="", encoding="utf-8-sig") as f:  # utf-8-sig + ; = Excel v CZ to otevre spravne
        w = csv.writer(f, delimiter=";")
        w.writerow(header)
        for r in rows:
            # bunka_csv: text zacinajici = + - @ by Excel spustil jako vzorec (CSV injection)
            w.writerow(["" if x is None else (f"{x:.2f}".replace(".", ",") if isinstance(x, float) else bunka_csv(x)) for x in r])
    return path


def run(con, cfg, today=None):
    today = today or date.today()
    since = today - timedelta(days=int(cfg["mesice"] * 30.5))
    nase = cfg.get("nase_ico") or None

    zak = [dict(z) for z in con.execute("SELECT * FROM zakazky")]
    dup = {r[0] for r in con.execute("SELECT objekt_id FROM priznaky WHERE typ='duplicita'")}
    zak = [z for z in zak if z["id"] not in dup]
    zmap = {z["id"]: z for z in zak}
    vit = [dict(v) for v in con.execute("SELECT * FROM vitezove") if v["zakazka_id"] in zmap]
    uc = [dict(u) for u in con.execute("SELECT * FROM ucastnici") if u["zakazka_id"] in zmap]
    firmy = {f["ico"]: dict(f) for f in con.execute("SELECT * FROM firmy")}

    def in_window(z):
        d = parse_date(z["datum_zahajeni"])
        return d is None or d >= since

    zw = [z for z in zak if in_window(z)]
    zw_ids = {z["id"] for z in zw}

    # ---------- KIQ1 ----------
    by_month = Counter((z["datum_zahajeni"] or "????-??")[:7] for z in zw)
    by_kraj = Counter(z["kraj"] or "neuvedeno" for z in zw)
    by_cpv = Counter(cpv_group(z["cpv_hlavni"]) for z in zw)
    hodnoty = [z["predpokladana_hodnota"] for z in zw if z["predpokladana_hodnota"]]
    top_val = sorted([z for z in zw if z["predpokladana_hodnota"]], key=lambda z: -z["predpokladana_hodnota"])[:10]
    kiq1 = {
        "pocet": len(zw), "celkova_hodnota": sum(hodnoty), "s_hodnotou": len(hodnoty),
        "po_mesicich": sorted(by_month.items()), "po_krajich": by_kraj.most_common(),
        "po_cpv": by_cpv.most_common(10), "top_hodnota": top_val,
    }

    # ---------- KIQ2: konkurenti ----------
    comp = defaultdict(lambda: {"vyhry": 0, "objem": 0.0, "ceny": [], "pomery": [], "zadavatele": set(), "cpv": Counter(),
                                "ucasti": 0, "overeno": 0, "nazev": None})
    for v in vit:
        if v["zakazka_id"] not in zw_ids:
            continue
        key = v["dodavatel_ico"] or ("?" + (v["dodavatel_nazev"] or ""))
        c = comp[key]
        c["nazev"] = c["nazev"] or v["dodavatel_nazev"]
        c["vyhry"] += 1
        c["overeno"] += v["overeno_rs"] or 0
        z = zmap[v["zakazka_id"]]
        if v["cena_bez_dph"]:
            c["objem"] += v["cena_bez_dph"]
            c["ceny"].append(v["cena_bez_dph"])
            if z["predpokladana_hodnota"]:
                c["pomery"].append(v["cena_bez_dph"] / z["predpokladana_hodnota"])
        c["zadavatele"].add(z["zadavatel_ico"])
        c["cpv"][cpv_group(z["cpv_hlavni"])] += 1
    for u in uc:
        if u["zakazka_id"] not in zw_ids:
            continue
        key = u["dodavatel_ico"] or ("?" + (u["dodavatel_nazev"] or ""))
        comp[key]["ucasti"] += 1
        comp[key]["nazev"] = comp[key]["nazev"] or u["dodavatel_nazev"]
    total_obj = sum(c["objem"] for c in comp.values()) or 1
    konkurenti = []
    for ico, c in comp.items():
        f = firmy.get(ico, {})
        ucasti = max(c["ucasti"], c["vyhry"]) if c["ucasti"] else None
        konkurenti.append({
            "ico": ico if not ico.startswith("?") else None,
            "nazev": f.get("nazev") or c["nazev"] or ico,
            "kraj": f.get("kraj"),
            "vyhry": c["vyhry"], "ucasti": ucasti,
            "win_rate": (c["vyhry"] / ucasti) if ucasti else None,
            "objem": c["objem"], "podil_trhu": c["objem"] / total_obj,
            "median_cena": _median(c["ceny"]),
            "median_pomer": _median(c["pomery"]),
            "zadavatelu": len(c["zadavatele"]),
            "top_segment": c["cpv"].most_common(1)[0][0] if c["cpv"] else None,
            "overeno_rs": c["overeno"],
            "nase": ico == nase,
        })
    konkurenti.sort(key=lambda k: (-k["objem"], -k["vyhry"]))

    # ---------- KIQ3: typicke podminky ----------
    krit = Counter()
    cena_only = 0
    with_krit = 0
    for z in zw:
        if z["kriteria"]:
            with_krit += 1
            parts = [norm(p) for p in z["kriteria"].split("|") if p.strip()]
            labels = set()
            for p in parts:
                if "cena" in p or "nabidkova" in p:
                    labels.add("cena")
                elif "kvalit" in p:
                    labels.add("kvalita")
                elif "termin" in p or "lhut" in p or "doba" in p:
                    labels.add("termín/doba plnění")
                elif "zkusen" in p or "realizacni tym" in p or "tym" in p:
                    labels.add("zkušenost týmu")
                elif "zarucn" in p or "zaruk" in p or "servis" in p:
                    labels.add("záruka/servis")
                elif "eko" in p or "emis" in p or "energ" in p:
                    labels.add("environmentální")
                elif "sankc" in p or "pokut" in p:
                    labels.add("sankce")
                else:
                    labels.add("jiné")
            krit.update(labels)
            if labels == {"cena"}:
                cena_only += 1
    pocty_nab = [z["pocet_nabidek"] for z in zw if z["pocet_nabidek"]]
    pomery_all = []
    for v in vit:
        z = zmap.get(v["zakazka_id"])
        if z and z["id"] in zw_ids and v["cena_bez_dph"] and z["predpokladana_hodnota"]:
            pomery_all.append(v["cena_bez_dph"] / z["predpokladana_hodnota"])
    kiq3 = {
        "median_hodnota": _median(hodnoty), "p25": _pct(hodnoty, .25), "p75": _pct(hodnoty, .75),
        "postupy": Counter(z["postup"] or "neuvedeno" for z in zw).most_common(6),
        "druhy": Counter(z["druh"] or "neuvedeno" for z in zw).most_common(4),
        "kriteria": krit.most_common(), "s_kriterii": with_krit, "jen_cena": cena_only,
        "prumer_nabidek": statistics.mean(pocty_nab) if pocty_nab else None,
        "jedna_nabidka": sum(1 for p in pocty_nab if p == 1), "s_poctem": len(pocty_nab),
        "median_pomer_cena": _median(pomery_all),
    }

    # ---------- KIQ4: prilezitosti ----------
    otevrene = [z for z in zak if _is_open(z, today)]
    zrusene = [z for z in zw if _is_cancelled(z)]

    # nabidky podle CPV skupiny (konkurencni intenzita)
    nab_cpv = defaultdict(list)
    for z in zak:
        if z["pocet_nabidek"]:
            nab_cpv[cpv_group(z["cpv_hlavni"])].append(z["pocet_nabidek"])
    # dominance konkurenta u zadavatele
    zad_wins = defaultdict(Counter)
    for v in vit:
        z = zmap[v["zakazka_id"]]
        zad_wins[z["zadavatel_ico"]][v["dodavatel_ico"] or v["dodavatel_nazev"]] += 1
    nase_ceny = [v["cena_bez_dph"] for v in vit if nase and v["dodavatel_ico"] == nase and v["cena_bez_dph"]]
    ref = nase_ceny if len(nase_ceny) >= 3 else hodnoty
    lo, hi = _pct(ref, .1), _pct(ref, .9)
    nazvy = {k["ico"]: k["nazev"] for k in konkurenti if k["ico"]}

    def score(z):
        s, why = 25, ["obor sedí (" + (z["relevance"] or "") + ")"]
        hv = z["predpokladana_hodnota"]
        if hv and lo and hi:
            if lo <= hv <= hi:
                s += 20; why.append("hodnota v našem obvyklém pásmu")
            elif hv > hi:
                s += 5; why.append("nadprůměrně velká zakázka (kapacity?)")
            else:
                s += 10; why.append("malá zakázka")
        else:
            s += 8; why.append("hodnota neuvedena")
        avg = statistics.mean(nab_cpv[cpv_group(z["cpv_hlavni"])]) if nab_cpv.get(cpv_group(z["cpv_hlavni"])) else None
        if avg is None:
            s += 10; why.append("konkurence v segmentu neznámá")
        elif avg <= 2:
            s += 20; why.append(f"nízká konkurence (Ø {str(round(avg, 1)).replace('.', ',')} nabídky)")
        elif avg <= 4:
            s += 12; why.append(f"střední konkurence (Ø {str(round(avg, 1)).replace('.', ',')} nabídky)")
        else:
            s += 4; why.append(f"vysoká konkurence (Ø {str(round(avg, 1)).replace('.', ',')} nabídky)")
        wins = zad_wins.get(z["zadavatel_ico"], Counter())
        if nase and wins.get(nase):
            s += 15; why.append(f"u zadavatele jsme vyhráli {wins[nase]}×")
        elif wins:
            top, n = wins.most_common(1)[0]
            tot = sum(wins.values())
            if tot >= 2 and n / tot > 0.5:
                s -= 10; why.append(f"zadavatel preferuje {nazvy.get(top, top)} ({n}/{tot} zakázek)")
            else:
                s += 5; why.append("zadavatel nemá dominantního dodavatele")
        d = parse_date(z["lhuta_nabidek"])
        days = (d - today).days if d else None
        if days is not None:
            if days >= 10:
                s += 10; why.append(f"{days} dní do podání")
            elif days >= 5:
                s += 4; why.append(f"jen {days} dní do podání")
            else:
                why.append(f"pouze {days} dní do podání!")
        s = max(0, min(100, s))
        dop = "BID" if s >= 60 else ("ZVÁŽIT" if s >= 40 else "NO-BID")
        return s, dop, why

    prilezitosti = []
    for z in otevrene:
        s, dop, why = score(z)
        prilezitosti.append({**z, "skore": s, "doporuceni": dop, "duvody": why})
    prilezitosti.sort(key=lambda p: -p["skore"])

    # ---------- KIQ5: nase pozice ----------
    kiq5 = None
    if nase:
        me = next((k for k in konkurenti if k["ico"] == nase), None)
        poradi = next((i + 1 for i, k in enumerate(konkurenti) if k["ico"] == nase), None)
        kiq5 = {"firma": firmy.get(nase, {}).get("nazev") or cfg.get("nas_nazev") or nase, "data": me, "poradi": poradi,
                "trh_median_pomer": kiq3["median_pomer_cena"], "konkurentu": len(konkurenti)}

    # ---------- smlouvy z Registru smluv (kontext) ----------
    rs = con.execute("""SELECT st.ico, MAX(st.nazev) nazev, COUNT(DISTINCT s.id) n, SUM(s.hodnota_bez_dph) h
                        FROM smlouvy s JOIN smlouvy_strany st ON st.smlouva_id=s.id
                        WHERE st.ico IS NOT NULL AND st.ico != s.zadavatel_ico GROUP BY st.ico ORDER BY h DESC LIMIT 15""").fetchall()
    rs_top = [dict(r) for r in rs]

    # ---------- CSV exporty ----------
    _write_csv("zakazky.csv", [[z["id"], z["nazev"], z["zadavatel_nazev"], z["zadavatel_ico"], z["cpv_hlavni"], z["kraj"],
                                 z["predpokladana_hodnota"], z["datum_zahajeni"], z["lhuta_nabidek"], z["stav"], z["pocet_nabidek"],
                                 z["kriteria"], z["url"]] for z in zw],
               ["id", "nazev", "zadavatel", "ico_zadavatele", "cpv", "kraj", "predpokladana_hodnota", "zahajeni", "lhuta_nabidek",
                "stav", "pocet_nabidek", "kriteria", "url"])
    _write_csv("konkurenti.csv", [[k["ico"], k["nazev"], k["kraj"], k["vyhry"], k["ucasti"], k["win_rate"], k["objem"],
                                    k["podil_trhu"], k["median_cena"], k["median_pomer"], k["zadavatelu"], k["top_segment"],
                                    k["overeno_rs"]] for k in konkurenti],
               ["ico", "nazev", "kraj", "vyhry", "ucasti", "win_rate", "objem_kc", "podil_trhu", "median_cena", "median_cena_vs_odhad",
                "pocet_zadavatelu", "hlavni_segment", "overeno_v_registru_smluv"])
    _write_csv("prilezitosti.csv", [[p["skore"], p["doporuceni"], p["nazev"], p["zadavatel_nazev"], p["predpokladana_hodnota"],
                                      p["lhuta_nabidek"], p["cpv_hlavni"], p["kraj"], "; ".join(p["duvody"]), p["url"]]
                                     for p in prilezitosti],
               ["skore", "doporuceni", "nazev", "zadavatel", "predpokladana_hodnota", "lhuta", "cpv", "kraj", "duvody", "url"])

    log(A, f"KIQ1: {len(zw)} zakazek | KIQ2: {len(konkurenti)} konkurentu | KIQ4: {len(otevrene)} otevrenych, "
           f"{len(zrusene)} zrusenych | CSV v {OUT_DIR}")
    return {"kiq1": kiq1, "konkurenti": konkurenti, "kiq3": kiq3, "prilezitosti": prilezitosti, "zrusene": zrusene,
            "kiq5": kiq5, "rs_top": rs_top, "obdobi_od": since.isoformat(), "dnes": today.isoformat()}
