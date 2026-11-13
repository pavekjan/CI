"""DEMO: cely workflow TenderScope na UMELYCH datech, bez internetu.

Vygeneruje falesne soubory ve stejnem formatu jako skutecne zdroje (RVZ ZIP s JSON, Registr smluv
index.xml + XML dump, ARES JSON, RSS), spusti lokalni web server a nasmeruje na nej agenty.
Vsechny firmy a zadavatele jsou VYMYSLENE. Slouzi k ukazce vystupu a k otestovani kodu.
"""
import http.server
import io
import json
import os
import random
import shutil
import socketserver
import threading
import webbrowser
import zipfile
from datetime import date, timedelta
from functools import partial

from ts import orchestrator
from ts.util import DATA_DIR, load_config, months_back

DEMO_DIR = os.path.join(DATA_DIR, "demo_server")


def make_ico(seed):
    base = f"{seed:07d}"[-7:]
    d = [int(c) for c in base]
    r = sum(d[i] * (8 - i) for i in range(7)) % 11
    c = 1 if r == 0 else (0 if r == 1 else 11 - r)
    return base + str(c)


# (nazev, segmenty, sila) - sila > 1 = casteji vyhrava
_F = [
    ("Alfa Software s.r.o.", "it", 1.0), ("Beta Systems a.s.", "it", 1.5), ("Gama Cloud s.r.o.", "it", 0.9),
    ("Delta IT Services a.s.", "it", 1.1), ("Epsilon Data s.r.o.", "it,hw", 1.0), ("Zeta Networks s.r.o.", "it,hw", 0.9),
    ("Theta Consulting a.s.", "it,sluzby", 1.2), ("Kappa Digital s.r.o.", "it,sluzby", 0.8), ("Lambda Infra a.s.", "hw", 1.0),
    ("Omega Soft s.r.o.", "it", 1.1), ("Stavby Horizont a.s.", "stavby", 1.6), ("Silnice Demo s.r.o.", "stavby", 1.2),
    ("Pozemní stavby Vzor s.r.o.", "stavby", 1.0), ("Inženýring Plus s.r.o.", "stavby,projekt", 1.1),
    ("Projekce Atelier s.r.o.", "projekt", 1.3), ("MedTech Ukázka a.s.", "zdravi", 1.4), ("Lékárenská Demo s.r.o.", "zdravi", 1.0),
    ("Čistota Příklad s.r.o.", "sluzby", 1.0), ("Energo Modelová a.s.", "stavby,hw", 0.9), ("Kancelář Fikce s.r.o.", "hw,sluzby", 0.8),
]
FIRMY = [(make_ico(2710000 + i * 37), n, set(seg.split(",")), sila) for i, (n, seg, sila) in enumerate(_F)]
NASE = FIRMY[4]
ZADAVATELE = [(make_ico(6000000 + i * 101), n) for i, n in enumerate([
    "Město Příkladov", "Krajský úřad Ukázkového kraje", "Ministerstvo pro demo data", "Nemocnice Vzorová, p.o.",
    "Vysoká škola Fiktivní", "Statutární město Testín", "Správa dat Demo, s.p.o.", "Obec Modelová",
    "Dopravní podnik Ukázka, a.s.", "Fakultní nemocnice Demo", "Ředitelství silnic Vzorového kraje", "Městská část Praha-Fikce"])]
NUTS = ["CZ010", "CZ020", "CZ064", "CZ080", "CZ071", "CZ032", "CZ052", "CZ042", "CZ063"]
PREDMETY = [("72212000", "it", "Vývoj a podpora informačního systému – {}"), ("72253000", "it", "Servisní podpora a helpdesk – {}"),
            ("48000000", "it", "Dodávka licencí software – {}"), ("30213100", "hw", "Dodávka notebooků – {}"),
            ("72317000", "it", "Cloudové služby a hosting – {}"), ("32420000", "hw", "Rozšíření sítě LAN – {}"),
            ("45233140", "stavby", "Rekonstrukce komunikace – {}"), ("45214000", "stavby", "Stavební úpravy budovy – {}"),
            ("45232400", "stavby", "Kanalizace a vodovod – {}"), ("71240000", "projekt", "Projektová dokumentace – {}"),
            ("71520000", "projekt", "Technický dozor stavebníka – {}"), ("33100000", "zdravi", "Zdravotnické přístroje – {}"),
            ("33600000", "zdravi", "Léčivé přípravky – {}"), ("90910000", "sluzby", "Úklidové služby – {}"),
            ("79340000", "sluzby", "Marketingová kampaň – {}")]
STAVY = ["Zadána", "Zadána", "Zadána", "Zadána", "Zrušena", "Probíhá"]
POSTUPY = ["Otevřené řízení", "Zjednodušené podlimitní řízení", "Zakázka malého rozsahu", "Jednací řízení bez uveřejnění"]


def gen_records(y, m, rnd, start_id):
    recs = []
    for i in range(rnd.randint(45, 70)):
        cpv, seg, tpl = rnd.choice(PREDMETY)
        zad = rnd.choice(ZADAVATELE)
        nasobek = 4 if seg == "stavby" else 1
        hod = round(rnd.choice([0.4, 0.8, 1.5, 2.5, 4, 7, 12, 25]) * nasobek * 1e6 * rnd.uniform(0.8, 1.2), -3)
        start = min(date(y, m, rnd.randint(1, 28)), date.today() - timedelta(days=rnd.randint(0, 10)))
        lhuta = start + timedelta(days=rnd.randint(15, 40))
        stav = rnd.choice(STAVY)
        if lhuta >= date.today():
            stav = "Probíhá"
        kandidati = [f for f in FIRMY if seg in f[2]]
        uchazeci = rnd.sample(kandidati, rnd.randint(1, min(5, len(kandidati))))
        if zad[1].startswith("Statutární") and seg == "it" and FIRMY[1] not in uchazeci and rnd.random() < .8:
            uchazeci = [FIRMY[1]] + uchazeci[:4]  # Beta Systems "dvorni dodavatel" Testína
        ceny = {f[0]: round(hod * rnd.uniform(0.7, 1.05), -2) for f in uchazeci}
        vitez = min(uchazeci, key=lambda f: ceny[f[0]] / (f[3] ** 0.5) * rnd.uniform(0.85, 1.15))
        krit = [{"nazev": "Nabídková cena", "vaha": 100}] if rnd.random() < .6 else \
               [{"nazev": "Nabídková cena", "vaha": 70}, {"nazev": "Kvalita realizačního týmu", "vaha": 30}]
        cast = {
            "cisloCasti": 1,
            "cpvHlavni": cpv,
            "cpvVedlejsi": [],
            "hodnoticiKriteria": krit,
            "pocetObdrzenychNabidek": len(uchazeci) if stav != "Probíhá" else None,
        }
        if stav == "Zadána":
            cast["ucastnici"] = [{"ico": f[0], "nazev": f[1], "nabidkovaCenaBezDPH": ceny[f[0]], "vybranyDodavatel": f == vitez}
                                 for f in uchazeci]
            cast["uzavreneSmlouvy"] = [{"datumUzavreni": (lhuta + timedelta(days=20)).isoformat(),
                                        "smluvniCenaBezDPH": ceny[vitez[0]],
                                        "dodavatel": {"ico": vitez[0], "nazev": vitez[1]}}]
        rid = f"RVZ{str(y)[2:]}{start_id + i:07d}"
        recs.append({
            "idVZ": rid,
            "nazevVZ": tpl.format(zad[1]),
            "zadavatel": {"ico": zad[0], "uredniNazev": zad[1]},
            "druhVZ": "Stavební práce" if cpv.startswith("45") else ("Dodávky" if cpv.startswith(("30", "32", "33", "48")) else "Služby"),
            "rezimVZ": "Podlimitní" if hod < 13e6 else "Nadlimitní",
            "druhZadavacihoPostupu": rnd.choice(POSTUPY),
            "stavVZ": stav,
            "predpokladanaHodnotaBezDPH": hod,
            "datumZahajeni": start.isoformat() + "T09:00:00",
            "lhutaProPodaniNabidek": lhuta.isoformat() + "T10:00:00",
            "mistoPlneni": {"kodNUTS": rnd.choice(NUTS)},
            "odkazNaZakazku": f"https://nen.nipez.cz/verejne-zakazky/detail-zakazky/{rid}",
            "casti": [cast],
        })
    # jedna duplicita (stejna zakazka z jineho nastroje)
    d = json.loads(json.dumps(recs[0]))
    d["idVZ"] = d["idVZ"] + "-VVZ"
    recs.append(d)
    return recs


def build_files(today):
    rnd = random.Random(42)
    if os.path.exists(DEMO_DIR):
        shutil.rmtree(DEMO_DIR)
    rvz_dir = os.path.join(DEMO_DIR, "rvz")
    os.makedirs(rvz_dir)
    all_recs = []
    months = months_back(13, today)
    for idx, (y, m) in enumerate(months):
        recs = gen_records(y, m, rnd, idx * 100)
        all_recs += recs
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            if idx % 3 == 0:  # nektere mesice jako JSON Lines, at otestujeme i tento format
                z.writestr(f"VZ-{m:02d}-{y}.jsonl", "\n".join(json.dumps(r, ensure_ascii=False) for r in recs))
            else:
                z.writestr(f"VZ-{m:02d}-{y}.json", json.dumps({"verze": "2.10.2", "verejneZakazky": recs}, ensure_ascii=False))
        with open(os.path.join(rvz_dir, f"VZ-{m:02d}-{y}.zip"), "wb") as f:
            f.write(buf.getvalue())

    # Registr smluv: smlouvy pro vetsinu vitezu + par dalsich
    sm_dir = os.path.join(DEMO_DIR, "smlouvy")
    os.makedirs(sm_dir)
    ns = "http://portal.gov.cz/rejstriky/ISRS/1.2/"
    zaznamy = []
    n = 0
    for r in all_recs:
        for c in r["casti"]:
            for s in c.get("uzavreneSmlouvy", []):
                if rnd.random() < 0.75:
                    n += 1
                    cena = s["smluvniCenaBezDPH"] * (1 if rnd.random() < .9 else 1.6)
                    zaznamy.append(f"""<zaznam><identifikator><idSmlouvy>{900000 + n}</idSmlouvy><idVerze>{800000 + n}</idVerze></identifikator>
<odkaz>https://smlouvy.gov.cz/smlouva/{800000 + n}</odkaz><casZverejneni>{s['datumUzavreni']}T12:00:00</casZverejneni>
<smlouva><subjekt><nazev>{r['zadavatel']['uredniNazev']}</nazev><ico>{r['zadavatel']['ico']}</ico></subjekt>
<smluvniStrana><nazev>{s['dodavatel']['nazev']}</nazev><ico>{s['dodavatel']['ico']}</ico></smluvniStrana>
<predmet>Smlouva: {r['nazevVZ']}</predmet><datumUzavreni>{s['datumUzavreni']}</datumUzavreni>
<hodnotaBezDph>{cena:.2f}</hodnotaBezDph><hodnotaVcetneDph>{cena * 1.21:.2f}</hodnotaVcetneDph></smlouva>
<platnyZaznam>1</platnyZaznam></zaznam>""")
    for k in range(15):  # dalsi IT smlouvy mimo RVZ (napr. male zakazky)
        f = rnd.choice(FIRMY)
        z = rnd.choice(ZADAVATELE)
        zaznamy.append(f"""<zaznam><identifikator><idSmlouvy>{950000 + k}</idSmlouvy></identifikator><odkaz>https://smlouvy.gov.cz/smlouva/{950000 + k}</odkaz>
<smlouva><subjekt><nazev>{z[1]}</nazev><ico>{z[0]}</ico></subjekt><smluvniStrana><nazev>{f[1]}</nazev><ico>{f[0]}</ico></smluvniStrana>
<predmet>Podpora software a licence</predmet><datumUzavreni>{today.isoformat()}</datumUzavreni><hodnotaBezDph>{rnd.randint(50, 900) * 1000}</hodnotaBezDph></smlouva>
<platnyZaznam>1</platnyZaznam></zaznam>""")
    with open(os.path.join(sm_dir, "dump_demo.xml"), "w", encoding="utf-8") as f:
        f.write(f'<?xml version="1.0" encoding="UTF-8"?><dump xmlns="{ns}"><mesic>{today.month}</mesic><rok>{today.year}</rok>'
                + "".join(zaznamy) + "</dump>")
    return all_recs


def write_index(port, today):
    sm_dir = os.path.join(DEMO_DIR, "smlouvy")
    with open(os.path.join(sm_dir, "index.xml"), "w", encoding="utf-8") as f:
        f.write(f"""<?xml version="1.0" encoding="UTF-8"?><index xmlns="http://portal.gov.cz/rejstriky/ISRS/1.2/">
<dump><mesic>{today.month}</mesic><rok>{today.year}</rok><hashDumpu algoritmus="sha2">x</hashDumpu><velikostDumpu>1</velikostDumpu>
<casGenerovani>{today.isoformat()}T01:00:00</casGenerovani><dokoncenyMesic>0</dokoncenyMesic>
<odkaz>http://127.0.0.1:{port}/smlouvy/dump_demo.xml</odkaz></dump></index>""")
    ares = os.path.join(DEMO_DIR, "ares")
    os.makedirs(ares, exist_ok=True)
    kraje = [("Hlavní město Praha", "110 00 Praha 1"), ("Jihomoravský kraj", "602 00 Brno"), ("Moravskoslezský kraj", "702 00 Ostrava")]
    nace_seg = [("stavby", ["41200", "42110"]), ("projekt", ["71120"]), ("zdravi", ["46460"]), ("sluzby", ["81210", "73110"]),
                ("hw", ["46510", "62090"]), ("it", ["62010", "62020"])]
    for i, (ico, nazev, segs, *_x) in enumerate(FIRMY):
        nace = next((n for sg, n in nace_seg if sg in segs), ["62010"])
        kraj, mesto = kraje[i % 3]
        with open(os.path.join(ares, ico), "w", encoding="utf-8") as f:
            json.dump({"ico": ico, "obchodniJmeno": nazev, "sidlo": {"textovaAdresa": f"Demo ulice {i + 1}, {mesto}",
                       "nazevKraje": kraj}, "czNace2008": nace, "pravniForma": "112",
                       "datumVzniku": "2010-01-01", **({"datumZaniku": "2026-06-30"} if i == 9 else {})}, f, ensure_ascii=False)
    with open(os.path.join(DEMO_DIR, "rss.xml"), "w", encoding="utf-8") as f:
        f.write("""<?xml version="1.0"?><rss><channel>
<item><title>Ukázková zpráva: stát chystá velký tendr na cloud (DEMO)</title><link>https://example.com/demo1</link><pubDate>Mon, 09 Nov 2026 08:00:00 GMT</pubDate><source>Demo zprávy</source></item>
<item><title>Ukázková zpráva: Beta Systems získala další zakázku (DEMO)</title><link>https://example.com/demo2</link><pubDate>Tue, 10 Nov 2026 08:00:00 GMT</pubDate><source>Demo IT</source></item>
</channel></rss>""")


class _Handler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def translate_path(self, path):
        if path.startswith("/rss"):
            path = "/rss.xml"
        return super().translate_path(path)


def _start_sources(today):
    """Vygeneruje umela data a spusti lokalni server, ktery se tvari jako statni zdroje."""
    build_files(today)
    handler = partial(_Handler, directory=DEMO_DIR)
    srv = socketserver.TCPServer(("127.0.0.1", 0), handler)
    port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    write_index(port, today)
    zdroje = {
        "rvz_base": f"http://127.0.0.1:{port}/rvz/",
        "smlouvy_base": f"http://127.0.0.1:{port}/smlouvy/",
        "ares_base": f"http://127.0.0.1:{port}/ares/",
        "hlidac_base": f"http://127.0.0.1:{port}/hlidac/",
        "zpravy_base": f"http://127.0.0.1:{port}/rss",
    }
    import ts.util as u
    import ts.sources.rvz as r
    import ts.sources.smlouvy as s
    cache = os.path.join(DATA_DIR, "demo_cache")
    shutil.rmtree(cache, ignore_errors=True)
    os.makedirs(cache)
    old = u.CACHE_DIR
    u.CACHE_DIR = r.CACHE_DIR = s.CACHE_DIR = cache
    return srv, zdroje, old


def _restore_cache(old):
    import ts.util as u
    import ts.sources.rvz as r
    import ts.sources.smlouvy as s
    u.CACHE_DIR = r.CACHE_DIR = s.CACHE_DIR = old


def build_demo_db(db_path):
    """Pro webovou aplikaci: postavi demo databazi (vsechny obory) pres stejne agenty jako ostry beh."""
    from ts import api, scout, verifier
    from ts.db import connect
    today = date.today()
    srv, zdroje, old = _start_sources(today)
    try:
        if os.path.exists(db_path):
            os.remove(db_path)
        cfg = load_config()
        cfg.update({"obor": "vse", "mesice": 12, "smlouvy_mesice": 1, "nase_ico": "", "hlidac_token": "",
                    "ares_max_firem": 100, "zdroje": zdroje})
        con = connect(db_path)
        scout.scout_rvz(con, cfg, today)
        scout.scout_smlouvy(con, cfg)
        scout.scout_ares(con, cfg)
        verifier.run(con)
        api.rebuild_index(con)
        con.close()
    finally:
        srv.shutdown()
        _restore_cache(old)


def main(open_browser=True):
    """Prikazova radka: demo briefu (puvodni CLI)."""
    today = date.today()
    print("DEMO: generuji umela data (vymyslene firmy a zadavatele)...")
    srv, zdroje, old = _start_sources(today)
    cfg = load_config()
    cfg.update({"obor": "it", "mesice": 12, "nase_ico": NASE[0], "hlidac_token": "", "zdroje": zdroje})
    import ts.analyst as an
    an.CSV_PREFIX = "DEMO_"
    db = os.path.join(DATA_DIR, "demo_brief.db")
    if os.path.exists(db):
        os.remove(db)
    try:
        res = orchestrator.run(cfg, auto_approve=True, today=today, db_path=db, typ="DEMO", suffix="_DEMO")
    finally:
        srv.shutdown()
        _restore_cache(old)
    if res:
        print(f"\nHotovo. Brief: {res['brief_html']}")
        if open_browser:
            webbrowser.open("file://" + os.path.abspath(res["brief_html"]))
    return res


if __name__ == "__main__":
    main()
