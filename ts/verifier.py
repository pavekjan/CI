"""Agent VERIFIER - krizova kontrola zdroju, duplicity, chybejici a podezrela data.

Kontroly:
  1. Platnost IČO (kontrolni cislice) u zadavatelu i dodavatelu.
  2. Duplicity: stejny nazev + zadavatel pod ruznymi ID (napr. zaznam NEN i Vestniku).
  3. Chybejici data: CPV, predpokladana hodnota, vitez u zadane zakazky, cena viteze.
  4. Krizove overeni viteze v Registru smluv (zadavatel + dodavatel + datum + cena).
  5. Odlehle hodnoty: smluvni cena vs. predpokladana hodnota.
  6. ARES: dodavatel zanikl / neexistuje.
"""
from collections import defaultdict
from datetime import timedelta

from .util import ico_valid, log, norm, parse_date

A = "Verifier"


def _flag(con, typ_obj, oid, typ, popis):
    con.execute("INSERT INTO priznaky VALUES (?,?,?,?)", (typ_obj, oid, typ, popis))


def run(con):
    con.execute("DELETE FROM priznaky")
    con.execute("UPDATE vitezove SET overeno_rs=0, smlouva_id=NULL")
    counts = defaultdict(int)

    zak = con.execute("SELECT * FROM zakazky").fetchall()
    # 1+3 chybejici / neplatne
    for z in zak:
        if z["zadavatel_ico"] and not ico_valid(z["zadavatel_ico"]):
            _flag(con, "zakazka", z["id"], "neplatne_ico", f"IČO zadavatele {z['zadavatel_ico']} nemá platnou kontrolní číslici")
            counts["neplatne_ico"] += 1
        if not z["cpv"]:
            _flag(con, "zakazka", z["id"], "chybi_cpv", "Chybí CPV kód")
            counts["chybi_cpv"] += 1
        if z["predpokladana_hodnota"] is None:
            _flag(con, "zakazka", z["id"], "chybi_hodnota", "Chybí předpokládaná hodnota")
            counts["chybi_hodnota"] += 1
        if not z["nazev"]:
            _flag(con, "zakazka", z["id"], "chybi_nazev", "Chybí název zakázky")
            counts["chybi_nazev"] += 1

    vit_by_z = defaultdict(list)
    for v in con.execute("SELECT * FROM vitezove"):
        vit_by_z[v["zakazka_id"]].append(v)
        if v["dodavatel_ico"] and not ico_valid(v["dodavatel_ico"]):
            _flag(con, "dodavatel", v["dodavatel_ico"], "neplatne_ico", f"IČO dodavatele {v['dodavatel_ico']} je neplatné (zahraniční?)")
            counts["neplatne_ico"] += 1
        if v["cena_bez_dph"] is None:
            counts["chybi_cena_viteze"] += 1
    for z in zak:
        st = norm(z["stav"])
        if any(w in st for w in ("zadan", "ukoncen", "uzavren", "dokoncen")) and not vit_by_z.get(z["id"]):
            _flag(con, "zakazka", z["id"], "chybi_vitez", "Zakázka je zadaná, ale v datech chybí vítěz")
            counts["chybi_vitez"] += 1

    # 2 duplicity: stejny nazev + zadavatel + blizke datum zahajeni (<= 45 dni) + shodna hodnota (+-2 %)
    #   (opakovane soutezi se stejnym nazvem v jinem obdobi duplicitou nejsou)
    groups = defaultdict(list)
    for z in zak:
        if z["nazev"] and z["zadavatel_ico"]:
            groups[(norm(z["nazev"]), z["zadavatel_ico"])].append(z)
    for items in groups.values():
        if len(items) < 2:
            continue
        items.sort(key=lambda z: (z["datum_zahajeni"] or "", z["id"]))
        kept = []
        for z in items:
            d = parse_date(z["datum_zahajeni"])
            orig = None
            for k in kept:
                dk = parse_date(k["datum_zahajeni"])
                same_date = d is None or dk is None or abs((d - dk).days) <= 45
                hv, hk = z["predpokladana_hodnota"], k["predpokladana_hodnota"]
                same_val = hv is None or hk is None or abs(hv - hk) <= 0.02 * max(hv, hk)
                if same_date and same_val:
                    orig = k
                    break
            if orig:
                _flag(con, "zakazka", z["id"], "duplicita", f"Pravděpodobná duplicita k {orig['id']}")
                counts["duplicita"] += 1
            else:
                kept.append(z)

    # 4 krizove overeni v Registru smluv
    zmap = {z["id"]: z for z in zak}
    overeno = 0
    for zid, vits in vit_by_z.items():
        z = zmap.get(zid)
        if not z or not z["zadavatel_ico"]:
            continue
        d0 = parse_date(z["datum_zahajeni"])
        for v in vits:
            if not v["dodavatel_ico"]:
                continue
            cands = con.execute("""SELECT s.* FROM smlouvy s JOIN smlouvy_strany st ON st.smlouva_id=s.id
                                   WHERE s.zadavatel_ico=? AND st.ico=?""", (z["zadavatel_ico"], v["dodavatel_ico"])).fetchall()
            best = None
            for s in cands:
                ds = parse_date(s["datum_uzavreni"])
                if d0 and ds and not (d0 - timedelta(days=30) <= ds <= d0 + timedelta(days=365)):
                    continue
                diff = None
                if v["cena_bez_dph"] and s["hodnota_bez_dph"]:
                    diff = abs(s["hodnota_bez_dph"] - v["cena_bez_dph"]) / max(v["cena_bez_dph"], 1)
                score = diff if diff is not None else 0.5
                if best is None or score < best[0]:
                    best = (score, s, diff)
            if best:
                _, s, diff = best
                con.execute("UPDATE vitezove SET overeno_rs=1, smlouva_id=? WHERE zakazka_id=? AND dodavatel_ico=?",
                            (s["id"], zid, v["dodavatel_ico"]))
                overeno += 1
                if diff is not None and diff > 0.25:
                    _flag(con, "zakazka", zid, "rozdil_ceny_rs",
                          f"Cena v RVZ {v['cena_bez_dph']:,.0f} Kč vs. Registr smluv {s['hodnota_bez_dph']:,.0f} Kč")
                    counts["rozdil_ceny_rs"] += 1

    # 5 odlehle hodnoty
    for z in zak:
        for v in vit_by_z.get(z["id"], []):
            if v["cena_bez_dph"] and z["predpokladana_hodnota"]:
                r = v["cena_bez_dph"] / z["predpokladana_hodnota"]
                if r > 3 or r < 0.2:
                    _flag(con, "zakazka", z["id"], "odlehla_cena",
                          f"Cena vítěze je {r:.0%} předpokládané hodnoty – ověřit (rámcová smlouva / chyba řádu?)")
                    counts["odlehla_cena"] += 1

    # 6 ARES
    for f in con.execute("SELECT * FROM firmy WHERE datum_zaniku IS NOT NULL AND datum_zaniku != ''"):
        _flag(con, "dodavatel", f["ico"], "firma_zanikla", f"{f['nazev']} zanikla {f['datum_zaniku']} (ARES)")
        counts["firma_zanikla"] += 1

    con.commit()
    n_vit = sum(len(v) for v in vit_by_z.values())
    summary = {
        "zakazek": len(zak),
        "vitezu": n_vit,
        "overeno_v_rs": overeno,
        "podil_overenych": (overeno / n_vit) if n_vit else 0.0,
        **counts,
    }
    log(A, f"zkontrolovano {len(zak)} zakazek, {overeno}/{n_vit} vitezu potvrzeno v Registru smluv, "
           f"duplicit {counts['duplicita']}, priznaku celkem {sum(counts.values())}")
    return summary
