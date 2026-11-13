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


FIRMY = [(make_ico(2710000 + i * 37), n) for i, n in enumerate([
    "Alfa Software s.r.o.", "Beta Systems a.s.", "Gama Cloud s.r.o.", "Delta IT Services a.s.", "Epsilon Data s.r.o.",
    "Zeta Networks s.r.o.", "Theta Consulting a.s.", "Kappa Digital s.r.o.", "Lambda Infra a.s.", "Omega Soft s.r.o."])]
NASE = FIRMY[4]  # "Epsilon Data" = nase firma v demu
ZADAVATELE = [(make_ico(6000000 + i * 101), n) for i, n in enumerate([
    "Město Příkladov", "Krajský úřad Ukázkového kraje", "Ministerstvo pro demo data", "Nemocnice Vzorová, p.o.",
    "Vysoká škola Fiktivní", "Statutární město Testín", "Správa dat Demo, s.p.o.", "Obec Modelová"])]
NUTS = ["CZ010", "CZ020", "CZ064", "CZ080", "CZ071", "CZ032", "CZ052"]
PREDMETY = [("72212000", "Vývoj a podpora informačního systému {}"), ("72253000", "Servisní podpora a helpdesk pro {}"),
            ("48000000", "Dodávka licencí software pro {}"), ("30213100", "Dodávka notebooků pro {}"),
            ("72317000", "Cloudové služby a hosting pro {}"), ("72700000", "Rozšíření sítě LAN v budově {}"),
            ("45000000", "Rekonstrukce chodníku u budovy {}"), ("79342000", "Kampaň a marketing {}")]
STAVY = ["Zadána", "Zadána", "Zadána", "Zadána", "Zrušena", "Probíhá"]
POSTUPY = ["Otevřené řízení", "Zjednodušené podlimitní řízení", "Zakázka malého rozsahu", "Jednací řízení bez uveřejnění"]


def gen_records(y, m, rnd, start_id):
    recs = []
    for i in range(rnd.randint(18, 30)):
        cpv, tpl = rnd.choice(PREDMETY)
        zad = rnd.choice(ZADAVATELE)
        hod = round(rnd.choice([0.4, 0.8, 1.5, 2.5, 4, 7, 12, 25]) * 1e6 * rnd.uniform(0.8, 1.2), -3)
        start = min(date(y, m, rnd.randint(1, 28)), date.today() - timedelta(days=rnd.randint(0, 10)))
        lhuta = start + timedelta(days=rnd.randint(15, 40))
        stav = rnd.choice(STAVY)
        if lhuta >= date.today():
            stav = "Probíhá"
        uchazeci = rnd.sample(FIRMY, rnd.randint(1, 5))
        if zad[1].startswith("Statutární") and rnd.random() < .8:
            uchazeci = [FIRMY[1]] + [f for f in uchazeci if f != FIRMY[1]]  # Beta dominuje u Testína
        ceny = {f[0]: round(hod * rnd.uniform(0.7, 1.05), -2) for f in uchazeci}
        vitez = min(uchazeci, key=lambda f: ceny[f[0]] * (0.85 if f == FIRMY[1] else 1))
        krit = [{"nazev": "Nabídková cena", "vaha": 100}] if rnd.random() < .6 else \
               [{"nazev": "Nabídková cena", "vaha": 70}, {"nazev": "Kvalita realizačního týmu", "vaha": 30}]
        cast = {
            "cisloCasti": 1,
            "cpvHlavni": cpv,
            "cpvVedlejsi": ["72000000"] if cpv.startswith("72") else [],
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
            "druhVZ": "Stavební práce" if cpv.startswith("45") else ("Dodávky" if cpv.startswith(("30", "48")) else "Služby"),
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
    kraje = ["Hlavní město Praha", "Jihomoravský kraj", "Moravskoslezský kraj"]
    for i, (ico, nazev) in enumerate(FIRMY):
        with open(os.path.join(ares, ico), "w", encoding="utf-8") as f:
            json.dump({"ico": ico, "obchodniJmeno": nazev, "sidlo": {"textovaAdresa": f"Demo ulice {i + 1}, Praha",
                       "nazevKraje": kraje[i % 3]}, "czNace2008": ["62010", "62020"], "pravniForma": "112",
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


def main(open_browser=True):
    today = date.today()
    print("DEMO: generuji umela data (vymyslene firmy a zadavatele)...")
    build_files(today)
    handler = partial(_Handler, directory=DEMO_DIR)
    srv = socketserver.TCPServer(("127.0.0.1", 0), handler)
    port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    write_index(port, today)

    cfg = load_config()
    cfg["obor"] = "it"
    cfg["mesice"] = 12
    cfg["nase_ico"] = NASE[0]
    cfg["hlidac_token"] = ""
    cfg["zdroje"] = {
        "rvz_base": f"http://127.0.0.1:{port}/rvz/",
        "smlouvy_base": f"http://127.0.0.1:{port}/smlouvy/",
        "ares_base": f"http://127.0.0.1:{port}/ares/",
        "hlidac_base": f"http://127.0.0.1:{port}/hlidac/",
        "zpravy_base": f"http://127.0.0.1:{port}/rss",
    }
    # demo pouziva vlastni databazi a cache, aby se nemichalo se skutecnymi daty
    import ts.util as u
    import ts.analyst as an
    an.CSV_PREFIX = "DEMO_"
    import ts.sources.rvz as r
    import ts.sources.smlouvy as s
    cache = os.path.join(DATA_DIR, "demo_cache")
    shutil.rmtree(cache, ignore_errors=True)
    os.makedirs(cache)
    u.CACHE_DIR = r.CACHE_DIR = s.CACHE_DIR = cache
    db = os.path.join(DATA_DIR, "demo.db")
    if os.path.exists(db):
        os.remove(db)
    res = orchestrator.run(cfg, auto_approve=True, today=today, db_path=db, typ="DEMO", suffix="_DEMO")
    srv.shutdown()
    if res:
        print(f"\nHotovo. Brief: {res['brief_html']}")
        if open_browser:
            webbrowser.open("file://" + os.path.abspath(res["brief_html"]))
    return res


if __name__ == "__main__":
    main()
