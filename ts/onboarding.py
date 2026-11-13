"""Agentni onboarding a Day-0 zpravodaj.

1. Recon agent      - z IČO (a volitelne webu) potichu sesbira: ARES, historii firmy v databazi zakazek
                      (vyhry, ucasti, CPV, zadavatele, kraje), Registr smluv, volitelne Hlidac statu, text webu.
2. Onboarding agent - Faze 1: hypoteza + 4 cilene otazky s quick_replies (JSON needs_clarification).
                      Faze 2: finalni company_profile JSON (CPV, negativni slova, NUTS 3, kvalifikace...).
                      S Claude API klicem rozhoduje model (prompt v ts/prompty/onboarding_system.md),
                      bez klice pravidlovy zaloznik se stejnym vystupnim formatem.
3. Backtest         - lokalni TF-IDF "embedding" popisu firmy + dotaznik vhodnosti kazde zakazky
                      (predmet, vzdalenost, velikost, cas, zadavatel, konkurence, kvalifikace, dealbreakery)
                      proti zakazkam za poslednich 14 dni -> prvni zpravodaj.

Zamerne bez PostgreSQL/pgvector: vse bezi v jednom souboru SQLite a jde spustit dvojklikem na Windows.
"""
import json
import math
import re
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta

from . import llm
from .api import CPV_DIV, _ares_cached, _median, cpv_group
from .util import NUTS_KRAJ, clean_ico, http_get, log, norm, parse_date

A = "Onboarding"

# ------------------------------------------------------------------ geografie
KRAJ_STRED = {  # krajska mesta (lat, lon); Stredocesky = priblizne teziste kraje
    "CZ010": (50.0755, 14.4378), "CZ020": (49.95, 14.55), "CZ031": (48.9745, 14.4743), "CZ032": (49.7384, 13.3736),
    "CZ041": (50.2319, 12.8711), "CZ042": (50.6607, 14.0323), "CZ051": (50.7671, 15.0562), "CZ052": (50.2092, 15.8328),
    "CZ053": (50.0343, 15.7812), "CZ063": (49.3961, 15.5912), "CZ064": (49.1951, 16.6068), "CZ071": (49.5938, 17.2509),
    "CZ072": (49.2265, 17.6707), "CZ080": (49.8209, 18.2625),
}
SOUSEDI = {
    "CZ010": ["CZ020"], "CZ020": ["CZ010", "CZ031", "CZ032", "CZ042", "CZ051", "CZ052", "CZ053", "CZ063"],
    "CZ031": ["CZ020", "CZ032", "CZ063", "CZ064"], "CZ032": ["CZ041", "CZ042", "CZ020", "CZ031"],
    "CZ041": ["CZ032", "CZ042"], "CZ042": ["CZ041", "CZ032", "CZ020", "CZ051"], "CZ051": ["CZ042", "CZ020", "CZ052"],
    "CZ052": ["CZ051", "CZ020", "CZ053"], "CZ053": ["CZ052", "CZ020", "CZ063", "CZ064", "CZ071"],
    "CZ063": ["CZ020", "CZ031", "CZ064", "CZ053"], "CZ064": ["CZ031", "CZ063", "CZ053", "CZ071", "CZ072"],
    "CZ071": ["CZ053", "CZ064", "CZ072", "CZ080"], "CZ072": ["CZ064", "CZ071", "CZ080"], "CZ080": ["CZ071", "CZ072"],
}
# vetsi mesta: nazev -> (lat, lon, NUTS3) - presnejsi vzdalenost nez krajske mesto
MESTA = {
    "praha": (50.0755, 14.4378, "CZ010"), "kladno": (50.147, 14.103, "CZ020"), "mlada boleslav": (50.411, 14.903, "CZ020"),
    "kolin": (50.028, 15.200, "CZ020"), "pribram": (49.690, 14.010, "CZ020"), "beroun": (49.964, 14.072, "CZ020"),
    "benesov": (49.782, 14.687, "CZ020"), "kutna hora": (49.948, 15.268, "CZ020"),
    "ceske budejovice": (48.9745, 14.4743, "CZ031"), "tabor": (49.414, 14.658, "CZ031"), "pisek": (49.309, 14.147, "CZ031"),
    "strakonice": (49.261, 13.902, "CZ031"), "jindrichuv hradec": (49.144, 15.003, "CZ031"),
    "plzen": (49.7384, 13.3736, "CZ032"), "klatovy": (49.395, 13.295, "CZ032"), "domazlice": (49.440, 12.930, "CZ032"),
    "karlovy vary": (50.2319, 12.8711, "CZ041"), "cheb": (50.080, 12.374, "CZ041"), "sokolov": (50.181, 12.640, "CZ041"),
    "usti nad labem": (50.6607, 14.0323, "CZ042"), "most": (50.503, 13.636, "CZ042"), "chomutov": (50.460, 13.417, "CZ042"),
    "teplice": (50.640, 13.824, "CZ042"), "decin": (50.773, 14.196, "CZ042"), "litomerice": (50.534, 14.132, "CZ042"),
    "louny": (50.357, 13.797, "CZ042"),
    "liberec": (50.7671, 15.0562, "CZ051"), "jablonec nad nisou": (50.724, 15.171, "CZ051"), "ceska lipa": (50.686, 14.538, "CZ051"),
    "hradec kralove": (50.2092, 15.8328, "CZ052"), "trutnov": (50.561, 15.913, "CZ052"), "nachod": (50.417, 16.163, "CZ052"),
    "jicin": (50.437, 15.351, "CZ052"),
    "pardubice": (50.0343, 15.7812, "CZ053"), "chrudim": (49.951, 15.795, "CZ053"), "svitavy": (49.756, 16.468, "CZ053"),
    "jihlava": (49.3961, 15.5912, "CZ063"), "trebic": (49.215, 15.882, "CZ063"), "zdar nad sazavou": (49.563, 15.939, "CZ063"),
    "havlickuv brod": (49.607, 15.581, "CZ063"), "pelhrimov": (49.431, 15.223, "CZ063"),
    "brno": (49.1951, 16.6068, "CZ064"), "znojmo": (48.855, 16.049, "CZ064"), "breclav": (48.759, 16.882, "CZ064"),
    "hodonin": (48.849, 17.132, "CZ064"), "vyskov": (49.277, 16.999, "CZ064"), "blansko": (49.363, 16.644, "CZ064"),
    "olomouc": (49.5938, 17.2509, "CZ071"), "prerov": (49.455, 17.451, "CZ071"), "prostejov": (49.472, 17.111, "CZ071"),
    "sumperk": (49.965, 16.970, "CZ071"),
    "zlin": (49.2265, 17.6707, "CZ072"), "uherske hradiste": (49.070, 17.460, "CZ072"), "kromeriz": (49.298, 17.393, "CZ072"),
    "vsetin": (49.339, 17.996, "CZ072"), "valasske mezirici": (49.472, 17.971, "CZ072"),
    "ostrava": (49.8209, 18.2625, "CZ080"), "opava": (49.938, 17.902, "CZ080"), "frydek mistek": (49.683, 18.350, "CZ080"),
    "karvina": (49.854, 18.543, "CZ080"), "havirov": (49.780, 18.430, "CZ080"), "novy jicin": (49.594, 18.010, "CZ080"),
    "trinec": (49.678, 18.672, "CZ080"),
}
SILNICNI_KOEF = 1.25  # vzdusna vzdalenost -> priblizne po silnici
LOKALNI_VERTIKALY = {"stavebnictvi", "facility_sluzby"}


def kraj_nuts(kraj_text):
    """'Moravskoslezský kraj' / 'Moravskoslezský' / 'CZ080' -> 'CZ080'."""
    if not kraj_text:
        return None
    s = str(kraj_text).upper().replace(" ", "")
    for k in NUTS_KRAJ:
        if s.startswith(k):
            return k
    n = norm(kraj_text).replace(" kraj", "").strip()
    for k, v in NUTS_KRAJ.items():
        if norm(v).startswith(n) or n.startswith(norm(v)):
            return k
    if "praha" in n:
        return "CZ010"
    return None


def nazev_kraje(nuts):
    return NUTS_KRAJ.get(nuts, "celá ČR" if nuts == "CZ0" else nuts or "neuvedeno")


def _mesto_z_adresy(adresa):
    """'Prumyslova 5, 70200 Ostrava - Moravska Ostrava' -> klic z MESTA nebo None."""
    if not adresa:
        return None
    m = re.search(r"\d{3}\s?\d{2}\s+([^,]+)", adresa)
    kandidati = [m.group(1)] if m else []
    kandidati += [p for p in adresa.split(",")[1:]]
    for k in kandidati:
        c = norm(re.split(r"\s+-\s+|\s+\d", k.strip())[0])
        for nazev in sorted(MESTA, key=len, reverse=True):
            if c == nazev or c.startswith(nazev + " "):
                return nazev
    return None


def sidlo_firmy(ares):
    """Souradnice sidla: mesto z adresy (kdyz sedi s krajem z ARES), jinak krajske mesto."""
    ares = ares or {}
    kn = kraj_nuts(ares.get("kraj"))
    mesto = _mesto_z_adresy(ares.get("sidlo"))
    if mesto and (kn is None or MESTA[mesto][2] == kn):
        lat, lon, kn2 = MESTA[mesto]
        return {"adresa": ares.get("sidlo"), "mesto": mesto.title(), "nuts3": kn2, "kraj": nazev_kraje(kn2), "lat": lat, "lon": lon,
                "presnost": "město"}
    if kn:
        lat, lon = KRAJ_STRED[kn]
        return {"adresa": ares.get("sidlo"), "mesto": None, "nuts3": kn, "kraj": nazev_kraje(kn), "lat": lat, "lon": lon,
                "presnost": "kraj"}
    return {"adresa": ares.get("sidlo"), "mesto": None, "nuts3": None, "kraj": None, "lat": None, "lon": None, "presnost": None}


def vzdalenost_km(a, b):
    (la1, lo1), (la2, lo2) = a, b
    p = math.pi / 180
    h = math.sin((la2 - la1) * p / 2) ** 2 + math.cos(la1 * p) * math.cos(la2 * p) * math.sin((lo2 - lo1) * p / 2) ** 2
    return 2 * 6371 * math.asin(math.sqrt(h)) * SILNICNI_KOEF


def misto_zakazky(z):
    kn = kraj_nuts(z.get("nuts")) or kraj_nuts(z.get("kraj"))
    return kn, (KRAJ_STRED.get(kn) if kn else None)


# ------------------------------------------------------------------ text / TF-IDF
STOP = set("""a i k o s u v z na do od po za ze se je to ve pro pri nebo jako ktery ktera ktere jsou byl byla bylo
bude jeho jejich nas vas tak take uz jen pouze jiz spol sro s.r.o a.s as cz www http https dodavka dodavky sluzby
sluzba smlouva smlouvy smlouvu prace zakazka zakazky verejna verejne mesto obec kraj krajsky urad ii iii iv the and for with""".split())


def tokeny(text):
    """Jednoduchy cesky 'stemmer': normalizace + prvnich 6 znaku slova (pokryje ohybani)."""
    out = []
    for w in norm(text).split():
        if len(w) < 3 or w in STOP or w.isdigit():
            continue
        out.append(w[:6])
    return out


class TfIdf:
    def __init__(self, dokumenty):
        self.n = len(dokumenty)
        df = Counter()
        for d in dokumenty:
            df.update(set(tokeny(d)))
        self.idf = {t: math.log((1 + self.n) / (1 + c)) + 1 for t, c in df.items()}

    def vektor(self, text):
        tf = Counter(tokeny(text))
        v = {t: (1 + math.log(c)) * self.idf.get(t, math.log(1 + self.n) + 1) for t, c in tf.items()}
        nrm = math.sqrt(sum(x * x for x in v.values())) or 1
        return {t: x / nrm for t, x in v.items()}

    @staticmethod
    def cos(a, b):
        if len(a) > len(b):
            a, b = b, a
        return sum(x * b.get(t, 0) for t, x in a.items())


def text_zakazky(z):
    cpvs = [c for c in (z.get("cpv") or "").split(",") if c]
    seg = " ".join(CPV_DIV.get(c[:2], "") for c in cpvs[:3])
    return f"{z.get('nazev') or ''} {seg}"


# ------------------------------------------------------------------ 1. RECON
def _web(url):
    if not url:
        return None
    from . import bezpecnost
    from .util import session
    try:
        # jen verejne adresy, kazde presmerovani se kontroluje, max. 1 MB (ochrana proti SSRF)
        status, html, url = bezpecnost.stahni_web(url, session())
        html = html if status == 200 else ""
    except bezpecnost.ChybaVstupu as e:
        return {"url": url, "chyba": str(e)}
    except Exception as e:
        return {"url": url, "chyba": type(e).__name__}
    if not html:
        return {"url": url, "chyba": f"HTTP {status}"}
    title = re.search(r"<title[^>]*>(.*?)</title>", html, re.S | re.I)
    desc = re.search(r'<meta[^>]+name=["\']description["\'][^>]+content=["\']([^"\']+)', html, re.I)
    body = re.sub(r"(?is)<(script|style|noscript|svg|nav|footer)[^>]*>.*?</\1>", " ", html)
    body = re.sub(r"(?s)<[^>]+>", " ", body)
    body = re.sub(r"&nbsp;|&#160;", " ", body)
    body = re.sub(r"\s+", " ", body).strip()
    return {"url": url, "titulek": (title.group(1).strip() if title else None),
            "popis": (desc.group(1).strip() if desc else None), "text": body[:4000]}


def _hlidac_smlouvy(cfg, ico):
    token = cfg.get("hlidac_token")
    if not token:
        return None
    base = cfg["zdroje"]["hlidac_base"]
    od = (date.today() - timedelta(days=3 * 365)).isoformat()
    try:
        r = http_get(f"{base}smlouvy/hledat", params={"dotaz": f"ico:{ico} podepsano:[{od} TO *]", "strana": 1, "razeni": 0},
                     headers={"Authorization": f"Token {token}"}, timeout=30, retries=1)
        if r.status_code != 200:
            return {"chyba": f"HTTP {r.status_code}"}
        res = r.json()
    except Exception as e:
        return {"chyba": str(e)[:120]}
    items = res.get("results") or res.get("Results") or res.get("data") or []
    out = []
    for s in items[:50]:
        platce = s.get("Platce") or s.get("platce") or {}
        out.append({"predmet": s.get("predmet") or s.get("Predmet"),
                    "hodnota": s.get("hodnotaBezDph") or s.get("CalculatedPriceWithVATinCZK") or s.get("hodnotaVcetneDph"),
                    "datum": (s.get("datumUzavreni") or "")[:10], "zadavatel": platce.get("nazev"), "zadavatel_ico": platce.get("ico")})
    return {"pocet": res.get("Total") or res.get("total") or len(out), "smlouvy": out}


def _historie(con, ico):
    """Co o firme vime z lokalni databaze zakazek a Registru smluv."""
    vyhry = [dict(r) for r in con.execute(
        """SELECT z.id, z.nazev, z.cpv_hlavni, z.zadavatel_ico, z.zadavatel_nazev, z.kraj, z.nuts, z.datum_zahajeni,
                  z.predpokladana_hodnota, v.cena_bez_dph FROM vitezove v JOIN zakazky z ON z.id=v.zakazka_id
           WHERE v.dodavatel_ico=?""", (ico,))]
    ucasti = con.execute("SELECT COUNT(DISTINCT zakazka_id) FROM ucastnici WHERE dodavatel_ico=?", (ico,)).fetchone()[0]
    ceny = [v["cena_bez_dph"] or v["predpokladana_hodnota"] for v in vyhry if (v["cena_bez_dph"] or v["predpokladana_hodnota"])]
    ceny.sort()
    q = (lambda p: ceny[min(len(ceny) - 1, int(p * len(ceny)))]) if ceny else (lambda p: None)
    cpv8 = Counter(v["cpv_hlavni"] for v in vyhry if v["cpv_hlavni"] and len(v["cpv_hlavni"]) >= 8)  # bez odhadu segmentu
    seg = Counter(cpv_group(v["cpv_hlavni"]) for v in vyhry)
    zad = defaultdict(lambda: {"pocet": 0, "objem": 0.0, "nazev": None})
    for v in vyhry:
        if v["zadavatel_ico"]:
            d = zad[v["zadavatel_ico"]]
            d["pocet"] += 1
            d["objem"] += v["cena_bez_dph"] or 0
            d["nazev"] = v["zadavatel_nazev"]
    kraje = Counter(kraj_nuts(v["nuts"]) or kraj_nuts(v["kraj"]) for v in vyhry)
    kraje.pop(None, None)
    rs = [dict(r) for r in con.execute(
        """SELECT s.predmet, s.hodnota_bez_dph, s.datum_uzavreni, s.zadavatel_ico, s.zadavatel_nazev
           FROM smlouvy_strany st JOIN smlouvy s ON s.id=st.smlouva_id WHERE st.ico=? ORDER BY s.datum_uzavreni DESC""", (ico,))]
    rs_zad = Counter((s["zadavatel_ico"], s["zadavatel_nazev"]) for s in rs if s["zadavatel_ico"])
    return {
        "vyher": len(vyhry), "ucasti": ucasti, "objem_czk": round(sum(v["cena_bez_dph"] or 0 for v in vyhry)),
        "median_zakazky_czk": _median(ceny), "p25_czk": q(0.25), "p75_czk": q(0.75), "max_czk": ceny[-1] if ceny else None,
        "top_cpv": [{"cpv": c, "pocet": n, "segment": cpv_group(c)} for c, n in cpv8.most_common(12)],
        # "neuvedeno" (zakazky bez CPV a bez odhadu) neni obor -> do profilu ani otazek nepatri
        "segmenty": [{"segment": s, "pocet": n} for s, n in seg.most_common(7) if s != "neuvedeno"][:6],
        "top_zadavatele": sorted(({"ico": k, **v} for k, v in zad.items()), key=lambda x: (-x["pocet"], -x["objem"]))[:10],
        "kraje": [{"nuts3": k, "kraj": nazev_kraje(k), "pocet": n} for k, n in kraje.most_common()],
        "nazvy_vyher": [v["nazev"] for v in sorted(vyhry, key=lambda x: x["datum_zahajeni"] or "", reverse=True)[:25]],
        "registr_smluv": {"pocet": len(rs), "objem_czk": round(sum(s["hodnota_bez_dph"] or 0 for s in rs)),
                          "predmety": [s["predmet"] for s in rs[:15]],
                          "top_smluvni_partneri": [{"ico": k[0], "nazev": k[1], "pocet": n} for k, n in rs_zad.most_common(8)]},
        "obdobi_dat": [r for r in con.execute("SELECT MIN(datum_zahajeni), MAX(datum_zahajeni) FROM zakazky").fetchone()],
    }


def recon(con, cfg, ico, web_url=None, online=True):
    ico = clean_ico(ico)
    if not ico:
        raise ValueError("Neplatné IČO")
    t0 = datetime.now()
    with ThreadPoolExecutor(max_workers=3) as ex:
        f_web = ex.submit(_web, web_url) if (web_url and online) else None
        f_hl = ex.submit(_hlidac_smlouvy, cfg, ico) if online else None
        ares = _ares_cached(con, cfg["zdroje"]["ares_base"], ico, online)  # SQLite jen z hlavniho vlakna
        hist = _historie(con, ico)
        web = f_web.result() if f_web else None
        hlidac = f_hl.result() if f_hl else None
    nazev = (ares or {}).get("nazev") or (con.execute("SELECT nazev FROM dodavatele WHERE ico=?", (ico,)).fetchone() or [None])[0]
    zdroje = [{"id": "ARES", "nazev": "ARES – ekonomické subjekty", "url": f"https://ares.gov.cz/ekonomicke-subjekty?ico={ico}", "rating": "A1", "ok": bool(ares)},
              {"id": "RVZ", "nazev": "Open data ISVZ (NEN, Věstník VZ)", "url": "https://isvz.nipez.cz/", "rating": "A1", "ok": hist["vyher"] + hist["ucasti"] > 0},
              {"id": "RS", "nazev": "Registr smluv", "url": "https://smlouvy.gov.cz/", "rating": "A1", "ok": hist["registr_smluv"]["pocet"] > 0}]
    if hlidac is not None:
        zdroje.append({"id": "HS", "nazev": "Hlídač státu – smlouvy (3 roky)", "url": f"https://www.hlidacstatu.cz/subjekt/{ico}", "rating": "B2", "ok": "chyba" not in hlidac})
    if web is not None:
        zdroje.append({"id": "WEB", "nazev": "Web firmy", "url": web.get("url"), "rating": "C3", "ok": "chyba" not in web})
    log(A, f"Recon {ico}: {nazev} – {hist['vyher']} výher, {hist['registr_smluv']['pocet']} smluv RS ({(datetime.now() - t0).total_seconds():.1f} s)")
    return {"ico": ico, "nazev": nazev or ico, "ares": ares, "sidlo": sidlo_firmy(ares), "historie": hist,
            "hlidac_statu": hlidac, "web": web, "zdroje": zdroje}


# ------------------------------------------------------------------ vertikala
VERT_CPV = {"45": "stavebnictvi", "44": "stavebnictvi", "43": "stavebnictvi", "71": "stavebnictvi",
            "72": "it_sw", "48": "it_sw", "30": "it_sw", "32": "it_sw",
            "90": "facility_sluzby", "50": "facility_sluzby", "77": "facility_sluzby", "55": "facility_sluzby", "98": "facility_sluzby",
            "79": "poradenstvi", "73": "poradenstvi", "80": "poradenstvi", "66": "poradenstvi"}
VERT_NACE = {"41": "stavebnictvi", "42": "stavebnictvi", "43": "stavebnictvi", "71": "stavebnictvi",
             "62": "it_sw", "63": "it_sw", "58": "it_sw", "81": "facility_sluzby", "80": "facility_sluzby", "56": "facility_sluzby",
             "69": "poradenstvi", "70": "poradenstvi", "73": "poradenstvi", "74": "poradenstvi", "85": "poradenstvi",
             "46": "dodavky_zbozi", "47": "dodavky_zbozi"}
# NACE (4 mista) -> (popis cinnosti, CPV kody); pro firmy bez historie ve verejnych zakazkach
NACE_CPV = {
    "4120": ("Pozemní stavby", ["45210000", "45211000", "45214000"]), "4211": ("Silnice a komunikace", ["45233000", "45233140"]),
    "4212": ("Železniční stavby", ["45234000"]), "4221": ("Vodovody a kanalizace", ["45231000", "45232400", "45232150"]),
    "4222": ("Energetické a telekomunikační sítě", ["45231400", "45232200"]), "4291": ("Vodní stavby", ["45240000"]),
    "4299": ("Inženýrské stavby", ["45220000"]), "4311": ("Demolice", ["45110000", "45111100"]),
    "4312": ("Příprava staveniště, zemní práce", ["45111000", "45112000"]),
    "4321": ("Elektroinstalace", ["45310000", "45311000", "45315000"]),
    "4322": ("Instalatérské práce, topení, VZT", ["45330000", "45331000", "45332000"]),
    "4329": ("Ostatní stavební instalace", ["45350000"]), "4331": ("Omítky a štukatérské práce", ["45410000"]),
    "4332": ("Truhlářské práce, okna, dveře", ["45420000", "45421000"]), "4333": ("Podlahy a obklady", ["45430000"]),
    "4334": ("Malířské a natěračské práce", ["45440000", "45442100"]), "4339": ("Dokončovací práce", ["45450000"]),
    "4391": ("Střechy", ["45261000"]), "4399": ("Specializované stavební práce", ["45262000"]),
    "7111": ("Architektonické služby", ["71200000", "71220000"]),
    "7112": ("Inženýrské služby, projekce, TDS", ["71300000", "71320000", "71520000"]),
    "6201": ("Vývoj software na zakázku", ["72200000", "72230000", "72212000"]), "6202": ("IT poradenství", ["72220000", "72224000"]),
    "6203": ("Správa IT systémů", ["72510000", "72500000"]), "6209": ("IT služby a podpora", ["72250000", "72253000"]),
    "6311": ("Hosting a zpracování dat", ["72400000", "72317000", "72300000"]),
    "8121": ("Úklid budov", ["90910000", "90911200", "90919200"]), "8122": ("Specializovaný úklid", ["90911000"]),
    "8129": ("Čištění a údržba veřejných prostor", ["90600000", "90610000"]), "8130": ("Údržba zeleně", ["77310000", "77311000", "77314000"]),
    "8010": ("Ostraha", ["79710000", "79713000"]), "8110": ("Správa budov", ["79993000", "50700000"]),
    "5610": ("Stravování", ["55300000", "55520000", "55321000"]), "5629": ("Závodní stravování", ["55500000", "55520000"]),
    "4646": ("Léčiva a zdravotnický materiál", ["33600000", "33140000"]), "4651": ("Výpočetní technika", ["30200000", "30213000"]),
    "4669": ("Stroje a zařízení", ["42000000"]), "7022": ("Poradenství v oblasti řízení", ["79410000", "79400000"]),
    "6910": ("Právní služby", ["79100000", "79110000"]), "6920": ("Účetnictví a audit", ["79200000", "79210000"]),
    "7311": ("Reklama a marketing", ["79340000", "79341000"]), "8559": ("Vzdělávání a školení", ["80500000", "80530000"]),
    "3811": ("Sběr odpadů", ["90510000", "90512000"]), "3812": ("Nebezpečný odpad", ["90520000"]),
    "4941": ("Nákladní doprava", ["60100000", "60161000"]), "3312": ("Opravy strojů", ["50500000", "50530000"]),
    "3320": ("Instalace strojů", ["51000000"]),
}


def nace_cpv(rc):
    """[(popis, [cpv...]), ...] podle NACE z ARES, v poradi (prvni = hlavni cinnost)."""
    out = []
    for n in ((rc.get("ares") or {}).get("nace") or "").split(","):
        n = n.strip()
        hit = NACE_CPV.get(n[:4]) if len(n) >= 4 else None  # 2-3mistny kod je moc obecny
        if hit and hit not in out:
            out.append(hit)
    return out


VERT_NAZEV = {"stavebnictvi": "stavebnictví", "it_sw": "IT a software", "facility_sluzby": "facility a služby",
              "dodavky_zbozi": "dodávky zboží", "poradenstvi": "poradenství", "jine": "jiný obor"}
VERT_CPV_DEFAULT = {"stavebnictvi": ["45000000", "45233000", "45210000"], "it_sw": ["72000000", "48000000", "72260000"],
                    "facility_sluzby": ["90910000", "50700000", "79710000"], "dodavky_zbozi": ["30190000", "39100000"],
                    "poradenstvi": ["79400000", "73000000"], "jine": []}
VERT_NEG = {"stavebnictvi": ["projektová dokumentace", "studie proveditelnosti", "technický dozor", "dodávka materiálu"],
            "it_sw": ["tonery", "kancelářský papír", "nábytek", "úklid"],
            "facility_sluzby": ["stavební práce", "projektová dokumentace", "software"],
            "dodavky_zbozi": ["stavební práce", "projektová dokumentace", "poradenství"],
            "poradenstvi": ["stavební práce", "dodávka", "úklid"], "jine": []}


def urci_vertikalu(rc):
    hlas = Counter()
    for c in rc["historie"]["top_cpv"]:
        v = VERT_CPV.get(c["cpv"][:2]) or ("dodavky_zbozi" if c["cpv"][:2] < "45" else None)
        if v:
            hlas[v] += c["pocet"]
    for i, n in enumerate(((rc.get("ares") or {}).get("nace") or "").split(",")):
        v = VERT_NACE.get(n.strip()[:2])
        if v:
            hlas[v] += 3 if i == 0 else 1
    return hlas.most_common(1)[0][0] if hlas else "jine"


def kc(x):
    if x is None:
        return "?"
    if x >= 1e9:
        return f"{x / 1e9:.1f}".replace(".", ",") + " mld. Kč"
    if x >= 1e6:
        return f"{x / 1e6:.1f}".replace(".", ",") + " mil. Kč"
    return f"{x / 1e3:.0f} tis. Kč"


# ------------------------------------------------------------------ 2a. FAZE 1 (pravidlovy zaloznik)
def faze1_pravidla(rc):
    h, s = rc["historie"], rc["sidlo"]
    vert = urci_vertikalu(rc)
    lokalni = vert in LOKALNI_VERTIKALY
    seg = [x["segment"] for x in h["segmenty"][:3]]
    zak = ", ".join(z["nazev"] for z in h["top_zadavatele"][:3] if z["nazev"])
    shr = (f"{rc['nazev']} ({s.get('mesto') or s.get('kraj') or 'sídlo neuvedeno'}) působí podle dat nejspíš v oboru {VERT_NAZEV[vert]}. ")
    if h["vyher"]:
        shr += (f"V databázi má {h['vyher']} vyhraných zakázek za {kc(h['objem_czk'])} (medián {kc(h['median_zakazky_czk'])})"
                + (f", hlavně v segmentech {', '.join(seg)}" if seg else "") + ". ")
        if zak:
            shr += f"Nejčastější zadavatelé: {zak}. "
    else:
        shr += "Ve stažených datech zatím žádnou vyhranou zakázku nemá, vycházím z ARES (NACE) a webu. "
    if h["registr_smluv"]["pocet"]:
        shr += f"V Registru smluv {h['registr_smluv']['pocet']} smluv za {kc(h['registr_smluv']['objem_czk'])}."

    q1 = [x["segment"].split(" ", 1)[-1] for x in h["segmenty"][:3] if x["segment"] != "neuvedeno"] or [p for p, _ in nace_cpv(rc)[:4]] or {
        "stavebnictvi": ["Pozemní stavby", "Silnice a komunikace", "Vodovody a kanalizace"],
        "it_sw": ["Vývoj software na zakázku", "Provoz a podpora IS", "Licence a cloud"],
        "facility_sluzby": ["Úklid", "Údržba budov", "Ostraha"],
        "dodavky_zbozi": ["Dodávky techniky", "Spotřební materiál", "Vybavení"],
        "poradenstvi": ["Právní a ekonomické poradenství", "Dotační management", "Školení"], "jine": ["Hlavní činnost firmy"]}[vert]
    q1 = q1 + [f"Vyhnout se: {VERT_NEG[vert][0]}"] if VERT_NEG[vert] else q1

    med = h["median_zakazky_czk"]
    q2 = ["VZMR do 2 mil. Kč (služby/dodávky) / 6 mil. (stavby)", "2–10 mil. Kč", "10–50 mil. Kč", "nad 50 mil. Kč"]
    if med:
        q2.insert(0, f"Jako dosud: {kc(h['p25_czk'])} – {kc(h['p75_czk'])}")
    q2 = q2[:4] + ["Příprava nabídky min. 10 dní"]

    if lokalni:
        q3 = [f"Jen {s['kraj']}" if s.get("kraj") else "Jen kraj sídla", "Kraj sídla + sousední kraje", "Do 100 km od sídla", "Celá ČR"]
        top_k = [k["kraj"] for k in h["kraje"][:2] if k["nuts3"] != s.get("nuts3")]
        if top_k:
            q3.insert(2, "Jako dosud: " + ", ".join([s.get("kraj") or ""] + top_k).strip(", "))
        q3_text = (f"Kam až jste ochotni jezdit? Sídlo máte v lokalitě {s.get('mesto') or s.get('kraj') or '?'}"
                   + (f", dosud jste plnili hlavně v krajích {', '.join(k['kraj'] for k in h['kraje'][:3])}." if h["kraje"] else "."))
        q3_cat = "Regiony a dojezd"
    else:
        q3 = ["Dodávka na klíč", "Bodyshopping / pronájem kapacit", "Obojí", "Celá ČR, osobní přítomnost jen výjimečně"]
        q3_text = "Jaký model spolupráce preferujete? (U vašeho oboru nehraje lokalita hlavní roli.)"
        q3_cat = "Forma plnění"

    q4 = {"stavebnictvi": ["Autorizace ČKAIT", "Stavbyvedoucí s praxí 5+ let", "ISO 9001 / 14001 / 45001", "Reference nad 10 mil. Kč", "Ochota jít do konsorcia / subdodávek"],
          "it_sw": ["ISO 27001", "Prověrka NBÚ", "Reference ve veřejné správě", "Certifikace výrobců (Microsoft, SAP, Cisco…)", "Ochota jít do konsorcia / subdodávek"],
          "facility_sluzby": ["Náhradní plnění (chráněný trh práce)", "ISO 9001", "Pojištění odpovědnosti 10+ mil. Kč", "Reference u nemocnic / úřadů", "Ochota jít do subdodávek"],
          "dodavky_zbozi": ["Autorizovaný distributor výrobce", "Vlastní servis", "ISO 9001", "Reference ve veřejné správě", "Ochota jít do konsorcia"],
          "poradenstvi": ["Odborná způsobilost / autorizace", "Reference ve veřejné správě", "ISO 9001", "Klíčoví experti s praxí 5+ let", "Ochota jít do konsorcia"],
          "jine": ["ISO 9001", "Reference ve veřejné správě", "Ochota jít do konsorcia / subdodávek"]}[vert]

    return {
        "status": "needs_clarification",
        "detected_summary": shr.strip(),
        "detected_vertical": vert,
        "questions": [
            {"id": "q1_scope", "category": "Předmět a exkluze",
             "question_text": "Co chcete hlídat přednostně a čemu se naopak vyhnout? (Můžete dopsat vlastní.)",
             "quick_replies": q1[:5], "allow_multiple": True},
            {"id": "q2_budget", "category": "Rozpočet a kapacita",
             "question_text": "Jak velké zakázky dávají smysl a kolik dní minimálně potřebujete na přípravu nabídky?",
             "quick_replies": q2[:5], "allow_multiple": True},
            {"id": "q3_region", "category": q3_cat, "question_text": q3_text, "quick_replies": q3[:5], "allow_multiple": False},
            {"id": "q4_qualification", "category": "Kvalifikace a oprávnění",
             "question_text": "Které z kvalifikačních předpokladů splňujete (ZZVZ § 77–79) a půjdete i do konsorcia?",
             "quick_replies": q4[:5], "allow_multiple": True},
        ],
    }


# ------------------------------------------------------------------ 2b. FAZE 2 (pravidlovy zaloznik)
def _odpoved_text(odp, qid):
    v = odp.get(qid) or {}
    sel = v.get("vybrano") or []
    return sel, (v.get("text") or "").strip()


def _castka(s):
    """'2–10 mil. Kč' -> (2e6, 10e6); 'nad 50 mil' -> (50e6, None); 'do 2 mil' -> (None, 2e6)."""
    t = norm(s)
    mult = 1e9 if "mld" in t else 1e6 if "mil" in t else 1e3 if "tis" in t else 1
    nums = [float(x.replace(",", ".")) * mult for x in re.findall(r"\d+(?:[.,]\d+)?", s.replace(" ", ""))]
    if not nums:
        return None, None
    if t.startswith("nad") or "a vic" in t:
        return nums[0], None
    if t.startswith("do ") or t.startswith("vzmr") or t.startswith("max"):
        return None, nums[0]
    return (nums[0], nums[1]) if len(nums) >= 2 else (nums[0], None)


def faze2_pravidla(rc, f1, odp):
    h, s = rc["historie"], rc["sidlo"]
    vert = f1.get("detected_vertical") or urci_vertikalu(rc)
    lokalni = vert in LOKALNI_VERTIKALY

    # Q1 predmet + exkluze
    sel1, txt1 = _odpoved_text(odp, "q1_scope")
    neg = []
    chci = []
    for x in sel1:
        if norm(x).startswith("vyhnout se"):
            neg.append(x.split(":", 1)[-1].strip())
        else:
            chci.append(x)
    for kus in re.split(r"[;,\n]", txt1):
        kus = kus.strip()
        if not kus:
            continue
        m = re.match(r"(?i)(ne|bez|vyhnout se|nechceme)\s*[:\-]?\s*(.+)", kus)
        (neg if m else chci).append(m.group(2).strip() if m else kus)
    neg += [n for n in VERT_NEG[vert] if n not in neg][:4]

    chci_seg = {norm(c) for c in chci}
    top = [c for c in h["top_cpv"] if not chci_seg or norm(CPV_DIV.get(c["cpv"][:2], "")) in chci_seg] or h["top_cpv"]
    main = [c["cpv"] for c in top[:5]]
    nc = nace_cpv(rc)
    vybrane_nace = [codes for label, codes in nc if norm(label) in chci_seg] or [codes for _, codes in nc[:1]]
    for codes in vybrane_nace:
        main += [c for c in codes if c not in main]
    main = main[:8] or VERT_CPV_DEFAULT[vert][:2]
    secondary = [c["cpv"] for c in h["top_cpv"] if c["cpv"] not in main][:8]
    secondary += [c for _, codes in nc for c in codes if c not in main and c not in secondary]
    secondary = secondary[:10] or VERT_CPV_DEFAULT[vert][2:]

    # Q2 rozpocet + priprava
    sel2, txt2 = _odpoved_text(odp, "q2_budget")
    lo = hi = None
    vzmr = False
    prep = 10
    for x in sel2 + [txt2]:
        if not x:
            continue
        nx = norm(x)
        if "priprav" in nx or "dni" in nx or "dnu" in nx:
            m = re.search(r"(\d+)\s*(dn|dní|dnů)", x)
            if m:
                prep = int(m.group(1))
            continue
        if nx.startswith("jako dosud"):
            a, b = h["p25_czk"], h["p75_czk"]
        else:
            a, b = _castka(x)
        if "vzmr" in nx:
            vzmr = True
            a = 0
        if a is not None:
            lo = a if lo is None else min(lo, a)
        if b is not None:
            hi = b if hi is None else max(hi, b)
        elif a is not None and not nx.startswith("jako dosud"):
            hi = None if hi is None or a >= (hi or 0) else hi
    if lo is None and hi is None and h["median_zakazky_czk"]:
        lo, hi = (h["p25_czk"] or 0) * 0.5, (h["p75_czk"] or 0) * 2
    if hi is None and not h["median_zakazky_czk"]:
        # firma bez historie a bez odpovedi: nedoporucovat megazakazky (metro za miliardy pro malou firmu)
        hi = {"stavebnictvi": 20e6, "it_sw": 10e6}.get(vert, 6e6)
        lo = lo or 0
        vzmr = True
    if lo is not None and lo < 2e6:
        vzmr = True

    # Q3 regiony / model spoluprace
    sel3, txt3 = _odpoved_text(odp, "q3_region")
    regiony, max_km, model = [], None, None
    volba = norm(" ".join(sel3) + " " + txt3)
    if lokalni:
        hq = s.get("nuts3")
        if "cela cr" in volba or "cela republika" in volba:
            regiony, max_km = ["CZ0"], None
        elif "km" in volba:
            m = re.search(r"(\d+)\s*km", volba)
            max_km = int(m.group(1)) if m else 100
            if s.get("lat"):
                regiony = [k for k, c in KRAJ_STRED.items() if vzdalenost_km((s["lat"], s["lon"]), c) <= max_km * 1.15 or k == hq]
        elif "soused" in volba and hq:
            regiony, max_km = [hq] + SOUSEDI[hq], 150
        elif "jako dosud" in volba:
            regiony, max_km = list(dict.fromkeys(([hq] if hq else []) + [k["nuts3"] for k in h["kraje"][:3]])), None
        elif hq:
            regiony, max_km = [hq], 80
        for k, v in NUTS_KRAJ.items():  # kraje dopsane textem
            if norm(v) in norm(txt3) and k not in regiony:
                regiony.append(k)
        regiony = regiony or ["CZ0"]
    else:
        regiony = ["CZ0"]
        model = ("obojí" if "oboji" in volba else "bodyshopping" if "body" in volba or "pronajem" in volba
                 else "na klíč" if "klic" in volba else None)

    # Q4 kvalifikace
    sel4, txt4 = _odpoved_text(odp, "q4_qualification")
    kval = [x for x in sel4 if "konsorc" not in norm(x) and "subdod" not in norm(x)]
    kval += [k.strip() for k in re.split(r"[;,\n]", txt4) if k.strip()]
    konsorcium = any("konsorc" in norm(x) or "subdod" in norm(x) for x in sel4) or "konsorc" in norm(txt4)

    dealbreakers = [f"lhůta na nabídku kratší než {prep} dní"]
    if hi:
        dealbreakers.append(f"zakázky nad {kc(hi * 1.5)} (mimo kapacitu)")
    if lokalni and max_km:
        dealbreakers.append(f"místo plnění dál než {max_km} km od sídla")
    dealbreakers += [f"předmět: {n}" for n in neg[:3]]

    # klicova slova z historie a webu
    txt = " ".join(h["nazvy_vyher"] + h["registr_smluv"]["predmety"] + [((rc.get("web") or {}).get("popis") or "")] + chci)
    stopz = {norm(z["nazev"] or "") for z in h["top_zadavatele"]}
    kw = [w for w, _ in Counter(w for w in norm(txt).split() if len(w) > 4 and w not in STOP and not any(w in z for z in stopz)).most_common(12)]

    seg_txt = ", ".join(CPV_DIV.get(c[:2], c) for c in dict.fromkeys(c[:2] for c in main))
    web = rc.get("web") or {}
    popis = (f"{rc['nazev']} se zaměřuje na {', '.join(chci) if chci else seg_txt or VERT_NAZEV[vert]}. "
             + (f"Typické zakázky: {'; '.join(h['nazvy_vyher'][:3])}. " if h["nazvy_vyher"] else "")
             + (f"Web: {web.get('popis') or web.get('titulek')}. " if web.get("popis") or web.get("titulek") else "")
             + (f"Kvalifikace: {', '.join(kval)}." if kval else ""))
    return {
        "status": "completed",
        "company_profile": {
            "ico": rc["ico"], "nazev": rc["nazev"], "vertical": vert, "core_capabilities_description": popis.strip(),
            "cpv_codes": {"main": main, "secondary": secondary}, "keywords": kw, "negative_keywords": neg,
            "regions_nuts3": regiony, "max_distance_km": max_km, "cooperation_model": model,
            "budget": {"min_czk": lo, "max_czk": hi, "vzmr_interest": vzmr}, "min_prep_days": prep,
            "qualifications": kval, "consortium_ok": konsorcium, "dealbreakers": dealbreakers,
            "whitelist_procurer_icos": [z["ico"] for z in h["top_zadavatele"][:8]], "blacklist_procurer_icos": [],
        },
    }


# ------------------------------------------------------------------ validace vystupu LLM
CPV8 = re.compile(r"^\d{8}$")


def _ocisti_faze1(d, zaloha):
    qs = [q for q in (d.get("questions") or []) if isinstance(q, dict) and isinstance(q.get("question_text"), str)]
    if len(qs) < 4:
        qs += zaloha["questions"][len(qs):]
    ids = ["q1_scope", "q2_budget", "q3_region", "q4_qualification"]
    for i, q in enumerate(qs[:4]):
        q["id"] = ids[i]
        qr = q.get("quick_replies") if isinstance(q.get("quick_replies"), list) else []
        q["quick_replies"] = [str(x)[:200] for x in qr][:5] or zaloha["questions"][i]["quick_replies"]
        q["question_text"] = q["question_text"][:600]
        q["allow_multiple"] = bool(q.get("allow_multiple", True))
        q["category"] = str(q.get("category") or zaloha["questions"][i].get("category") or "")[:60]
    d["questions"] = qs[:4]
    if not isinstance(d.get("detected_summary"), str) or not d["detected_summary"].strip():
        d["detected_summary"] = zaloha["detected_summary"]
    d["detected_summary"] = d["detected_summary"][:2000]
    if d.get("detected_vertical") not in llm.VERTIKALY:
        d["detected_vertical"] = zaloha["detected_vertical"]
    d["status"] = "needs_clarification"
    return d


def _ocisti_profil(p, zaloha, rc):
    z = zaloha["company_profile"]
    p = {**z, **{k: v for k, v in p.items() if v not in (None, "", [])}} if p else dict(z)
    p["ico"], p["nazev"] = rc["ico"], rc["nazev"]
    cpv = p.get("cpv_codes") or {}
    fix = lambda xs: [c[:8] for c in (str(x).replace("-", "") for x in xs or []) if CPV8.match(c[:8])]
    p["cpv_codes"] = {"main": fix(cpv.get("main")) or z["cpv_codes"]["main"], "secondary": fix(cpv.get("secondary"))}
    p["regions_nuts3"] = [r for r in (p.get("regions_nuts3") or []) if r in NUTS_KRAJ or r == "CZ0"] or z["regions_nuts3"]
    p["whitelist_procurer_icos"] = [i for i in (clean_ico(x) for x in p.get("whitelist_procurer_icos") or []) if i]
    p["blacklist_procurer_icos"] = [i for i in (clean_ico(x) for x in p.get("blacklist_procurer_icos") or []) if i]
    b = p.get("budget") or {}
    zb = z.get("budget") or {}
    p["budget"] = {"min_czk": b.get("min_czk") if b.get("min_czk") is not None else zb.get("min_czk"),
                   "max_czk": b.get("max_czk") if b.get("max_czk") is not None else zb.get("max_czk"),
                   "vzmr_interest": bool(b.get("vzmr_interest", zb.get("vzmr_interest")))}
    p["min_prep_days"] = int(p.get("min_prep_days") or 10)
    try:  # rocni obrat firmy (zadava uzivatel) - pro odhad kvalifikace; ARES ho neuvadi
        p["obrat_czk"] = max(0.0, min(float(p.get("obrat_czk") or 0), 1e12)) or None
    except (TypeError, ValueError):
        p["obrat_czk"] = None
    p["sidlo"] = rc["sidlo"]
    return p


# ------------------------------------------------------------------ verejne API
# Vlastnictvi (pravidlo 2): kazdy zaznam patri vlastnikovi. "" = spravce / lokalni aplikace,
# "u:<hash>" = anonymni navstevnik online verze. Kazdy dotaz filtruje podle vlastnika,
# cizi zaznam se tvari jako neexistujici.
_SCHEMA = ("CREATE TABLE IF NOT EXISTS onboarding_v2 (ico TEXT, vlastnik TEXT NOT NULL DEFAULT '', recon TEXT, faze1 TEXT, "
           "odpovedi TEXT, profil TEXT, upraveno TEXT, PRIMARY KEY (ico, vlastnik))")


def _tabulka(con):
    con.execute(_SCHEMA)
    stara = con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='onboarding'").fetchone()
    if stara:  # prevod z verze bez vlastnika: stare profily patri spravci
        con.execute("INSERT OR IGNORE INTO onboarding_v2 (ico,vlastnik,recon,faze1,odpovedi,profil,upraveno) "
                    "SELECT ico,'',recon,faze1,odpovedi,profil,upraveno FROM onboarding")
        con.execute("DROP TABLE onboarding")
        con.commit()


def _ulozit(con, ico, vlastnik="", **kw):
    _tabulka(con)
    row = con.execute("SELECT * FROM onboarding_v2 WHERE ico=? AND vlastnik=?", (ico, vlastnik)).fetchone()
    cur = dict(row) if row else {"ico": ico, "vlastnik": vlastnik, "recon": None, "faze1": None, "odpovedi": None, "profil": None}
    for k, v in kw.items():
        cur[k] = json.dumps(v, ensure_ascii=False, default=str)
    cur["upraveno"] = datetime.now().isoformat(timespec="seconds")
    con.execute("INSERT OR REPLACE INTO onboarding_v2 (ico,vlastnik,recon,faze1,odpovedi,profil,upraveno) "
                "VALUES (:ico,:vlastnik,:recon,:faze1,:odpovedi,:profil,:upraveno)", cur)
    con.commit()


def nacti(con, ico, vlastnik=""):
    _tabulka(con)
    row = con.execute("SELECT * FROM onboarding_v2 WHERE ico=? AND vlastnik=?", (clean_ico(ico) or ico, vlastnik)).fetchone()
    if not row:
        return None
    return {k: (json.loads(row[k]) if row[k] and k not in ("ico", "upraveno") else row[k])
            for k in row.keys() if k != "vlastnik"}


def seznam(con, vlastnik=""):
    _tabulka(con)
    out = []
    for r in con.execute("SELECT ico, profil, recon, upraveno FROM onboarding_v2 WHERE vlastnik=? ORDER BY upraveno DESC", (vlastnik,)):
        p = json.loads(r["profil"]) if r["profil"] else None
        rc = json.loads(r["recon"]) if r["recon"] else {}
        out.append({"ico": r["ico"], "nazev": (p or {}).get("nazev") or rc.get("nazev"), "hotovo": bool(p),
                    "vertical": (p or {}).get("vertical"), "upraveno": r["upraveno"]})
    return out


def _recon_pro_llm(rc):
    """Zkraceny vstup pro model (bez velkych poli)."""
    d = json.loads(json.dumps(rc, default=str))
    if d.get("web") and d["web"].get("text"):
        d["web"]["text"] = d["web"]["text"][:3000]
    return d


def _ai(cfg, payload, schema, ocisti, llm_povolit, faze):
    """Zavola vybraneho AI poskytovatele. Vraci (vycisteny vysledek nebo None, info pro frontend).
    Cokoli se pokazi (klic, sit, limit, nesmyslna odpoved), vraci None a onboarding pouzije pravidla."""
    n = llm.nastaveni(cfg)
    if not n:
        return None, {"rezim": "pravidla", "duvod": "AI není nastavená (Data → Umělá inteligence)"}
    if llm_povolit and not llm_povolit():
        return None, {"rezim": "pravidla", "duvod": "denní limit volání AI vyčerpán"}
    try:
        d, meta = llm.zavolej(n, payload, schema)
        return ocisti(d), {"rezim": "llm", **meta}
    except Exception as e:
        duvod = f"{n['nazev']}: {llm.chyba_text(e)}"
        log(A, f"Faze {faze} pres AI selhala ({duvod}), pouzivam pravidla")
        return None, {"rezim": "pravidla", "duvod": duvod}


def start(con, cfg, ico, web_url=None, online=True, vlastnik="", llm_povolit=None):
    """Recon + Faze 1. Vraci JSON pro frontend."""
    rc = recon(con, cfg, ico, web_url, online)
    zaloha = faze1_pravidla(rc)
    f1, info = _ai(cfg, {"faze": 1, "recon": _recon_pro_llm(rc)}, llm.SCHEMA_FAZE1,
                   lambda d: _ocisti_faze1(d, zaloha), llm_povolit, 1)
    f1 = f1 or zaloha
    _ulozit(con, rc["ico"], vlastnik, recon=rc, faze1=f1, odpovedi=None, profil=None)
    return {"recon": rc, "faze1": f1, "agent": info}


def dokonci(con, cfg, ico, odpovedi, today=None, vlastnik="", llm_povolit=None):
    """Faze 2 + backtest. odpovedi = {qid: {"vybrano": [...], "text": "..."}}"""
    st = nacti(con, ico, vlastnik)
    if not st or not st.get("recon"):
        raise ValueError("Nejdřív spusťte první krok onboardingu.")
    rc, f1 = st["recon"], st["faze1"]
    zaloha = faze2_pravidla(rc, f1, odpovedi)
    profil, info = _ai(cfg, {"faze": 2, "recon": _recon_pro_llm(rc), "otazky": f1, "odpovedi": odpovedi}, llm.SCHEMA_FAZE2,
                       lambda d: _ocisti_profil(d.get("company_profile") if isinstance(d.get("company_profile"), dict) else None,
                                                zaloha, rc), llm_povolit, 2)
    profil = profil or _ocisti_profil(None, zaloha, rc)
    _ulozit(con, rc["ico"], vlastnik, odpovedi=odpovedi, profil=profil)
    return {"status": "completed", "company_profile": profil, "agent": info, "zpravodaj": zpravodaj(con, profil, today)}


def uloz_profil(con, ico, profil, today=None, vlastnik=""):
    st = nacti(con, ico, vlastnik)
    if not st:
        raise ValueError("Profil nenalezen. Nejdřív projděte onboarding.")
    rc = st.get("recon") or {"ico": ico, "nazev": profil.get("nazev"), "sidlo": profil.get("sidlo") or {}}
    profil = _ocisti_profil(profil, {"company_profile": profil}, rc)
    _ulozit(con, clean_ico(ico) or ico, vlastnik, profil=profil)
    return {"company_profile": profil, "zpravodaj": zpravodaj(con, profil, today)}


# ------------------------------------------------------------------ 3. DOTAZNIK VHODNOSTI + ZPRAVODAJ
VAHY = {"predmet": 30, "lokalita": 20, "velikost": 15, "cas": 10, "zadavatel": 10, "konkurence": 10, "kvalifikace": 15}


def kapacita(con, ico, today=None):
    """Co firma prokazatelne zvlada podle verejnych dat (pro odhad kvalifikace):
    - verejne trzby za 12 mesicu = vyhry v RVZ + smlouvy v Registru smluv (spodni odhad obratu),
    - reference po oborech CPV: vyhrane zakazky za 3 roky (pocet a hodnoty)."""
    today = today or date.today()
    od12, od36 = (today - timedelta(days=365)).isoformat(), (today - timedelta(days=3 * 365)).isoformat()
    rvz12 = con.execute("""SELECT COALESCE(SUM(v.cena_bez_dph), 0) FROM vitezove v JOIN zakazky z ON z.id=v.zakazka_id
                           WHERE v.dodavatel_ico=? AND z.datum_zahajeni >= ?""", (ico, od12)).fetchone()[0]
    rs12 = con.execute("SELECT COALESCE(SUM(hodnota), 0) FROM smlouvy_souhrn WHERE ico=? AND mesic >= ?", (ico, od12[:7])).fetchone()[0]
    ref = defaultdict(list)
    for cpv, cena, odhad in con.execute("""SELECT z.cpv_hlavni, v.cena_bez_dph, z.predpokladana_hodnota FROM vitezove v
                                           JOIN zakazky z ON z.id=v.zakazka_id WHERE v.dodavatel_ico=? AND z.datum_zahajeni >= ?""",
                                        (ico, od36)):
        h = cena or odhad
        if cpv and h:
            ref[cpv[:2]].append(h)
    return {"verejne_trzby_12m": (rvz12 or 0) + (rs12 or 0), "reference": dict(ref)}


def _kvalifikace(z, profil, kap):
    """Splni firma pravdepodobne kvalifikaci? Bez textu zadavaci dokumentace jde jen o odhad:
    - obrat: zadavatel smi pozadovat nejvyse 2x predpokladanou hodnotu (ZZVZ § 78 odst. 3); kdyz zdroj uvadi
      pozadovany obrat, pouzije se ten,
    - reference: zadavatele obvykle chteji 2-3 obdobne zakazky srovnatelneho rozsahu za posledni 3 (stavby 5) let.
    Vraci (skore nebo None, odpoved, ko)."""
    hod = z.get("predpokladana_hodnota")
    pozad = z.get("min_obrat")
    obrat_zadany = (profil.get("obrat_czk") or 0) or None
    obrat = obrat_zadany or ((kap or {}).get("verejne_trzby_12m") or None)
    casti, sk, ko = [], [], None
    if z.get("kvalifikace"):
        casti.append(f"zadavatel uvádí: {z['kvalifikace'][:220]}")
    if (pozad or hod) and obrat:
        nejvic = pozad or 2 * hod  # nejprisnejsi mozny pozadavek
        typicky = pozad or hod
        zdroj = "váš obrat" if obrat_zadany else "vaše veřejné tržby za 12 měsíců"
        if obrat >= nejvic:
            sk.append(100)
            casti.append(f"{zdroj} {kc(obrat)} pokryje i nejpřísnější možný požadavek na obrat ({kc(nejvic)})")
        elif obrat >= typicky:
            sk.append(70)
            casti.append(f"{zdroj} {kc(obrat)} nejspíš stačí (požadavek bývá do {kc(nejvic)})")
        elif obrat >= 0.5 * typicky:
            sk.append(40)
            casti.append(f"{zdroj} {kc(obrat)} je na hraně – zvažte konsorcium")
        else:
            sk.append(10)
            casti.append(f"{zdroj} {kc(obrat)} je výrazně pod hodnotou zakázky")
            if obrat_zadany and not profil.get("consortium_ok"):
                ko = f"požadovaný obrat (až {kc(nejvic)}) výrazně převyšuje váš obrat {kc(obrat)}"
    elif (pozad or hod) and not obrat:
        casti.append("obrat neznáme – doplňte ho v profilu")
    oddil = (z.get("cpv_hlavni") or "")[:2]
    refs = ((kap or {}).get("reference") or {}).get(oddil) or []
    if hod and oddil:
        srovnatelne = [r for r in refs if r >= 0.5 * hod]
        sk.append(100 if len(srovnatelne) >= 2 else 70 if srovnatelne else 45 if refs else 25)
        casti.append(f"srovnatelné reference v oboru za 3 roky: {len(srovnatelne)}"
                     + (f" (celkem {len(refs)} zakázek, největší {kc(max(refs))})" if refs else " (z veřejných zakázek žádné)"))
    q = profil.get("qualifications") or []
    if q:
        casti.append("v profilu: " + ", ".join(q[:3]))
    if profil.get("consortium_ok") and sk:
        sk = [max(s, 50) for s in sk]
        casti.append("chybějící kvalifikaci můžete doplnit konsorciem/poddodavatelem")
    skore = round(sum(sk) / len(sk)) if sk else (75 if q else None)
    casti.append("přesné podmínky ověřte v zadávací dokumentaci")
    return skore, "; ".join(casti), ko


def _konkurence(con):
    """Pro segment: prumerny pocet nabidek a podil nejvetsiho dodavatele."""
    seg = defaultdict(lambda: {"nab": [], "dod": Counter()})
    for r in con.execute("SELECT z.cpv_hlavni, z.pocet_nabidek, v.dodavatel_ico FROM vitezove v JOIN zakazky z ON z.id=v.zakazka_id"):
        s = seg[(r["cpv_hlavni"] or "")[:2]]
        if r["pocet_nabidek"]:
            s["nab"].append(r["pocet_nabidek"])
        s["dod"][r["dodavatel_ico"]] += 1
    nab_z = defaultdict(list)
    for r in con.execute("SELECT z.cpv_hlavni, COUNT(*) n FROM ucastnici u JOIN zakazky z ON z.id=u.zakazka_id GROUP BY u.zakazka_id"):
        nab_z[(r["cpv_hlavni"] or "")[:2]].append(r["n"])
    out = {}
    for k, s in seg.items():
        nab = s["nab"] or nab_z.get(k) or []
        tot = sum(s["dod"].values())
        out[k] = {"prumer_nabidek": (sum(nab) / len(nab)) if nab else None,
                  "top_podil": (s["dod"].most_common(1)[0][1] / tot) if tot else None, "vitezu": len(s["dod"])}
    return out


def vhodnost(z, profil, tf, qv, konk, today, klienti=(), kap=None):
    """Kvalitativni dotaznik: pro kazdou otazku odpoved, skore 0-100 a duvod. KO = vylucujici."""
    kr = []
    ko = []
    cpvs = [c for c in (z.get("cpv") or "").split(",") if c] or ([z["cpv_hlavni"]] if z.get("cpv_hlavni") else [])
    main, sec = profil["cpv_codes"]["main"], profil["cpv_codes"].get("secondary") or []

    # 1 predmet
    def cpv_sk(c):
        best = 0
        for m in main:
            best = max(best, 100 if c[:5] == m[:5] else 80 if c[:3] == m[:3] else 55 if c[:2] == m[:2] else 0)
        for m in sec:
            best = max(best, 70 if c[:5] == m[:5] else 45 if c[:3] == m[:3] else 30 if c[:2] == m[:2] else 0)
        return best
    cs = max([cpv_sk(c) for c in cpvs] or [0])
    sim = TfIdf.cos(qv, tf.vektor(text_zakazky(z))) if tf else 0
    sk = round(min(100, max(cs, 0) * 0.7 + min(1, sim * 2.5) * 100 * 0.3 + (15 if cs == 0 and sim > 0.25 else 0)))
    kr.append({"klic": "predmet", "otazka": "Odpovídá předmět tomu, co děláme?",
               "odpoved": f"CPV {', '.join(cpvs[:2]) or '?'} – shoda s profilem {cs} %, textová podobnost {sim:.2f}", "skore": sk})

    # 2 lokalita
    kn, misto = misto_zakazky(z)
    s = profil.get("sidlo") or {}
    lokalni = profil.get("vertical") in LOKALNI_VERTIKALY
    if misto and s.get("lat"):
        km = round(vzdalenost_km((s["lat"], s["lon"]), misto))
        limit = profil.get("max_distance_km") or (150 if lokalni else None)
        v_regionu = "CZ0" in profil["regions_nuts3"] or kn in profil["regions_nuts3"]
        if lokalni:
            sk = 100 if km <= (limit or 150) * 0.6 else max(0, round(100 - (km - (limit or 150) * 0.6) / ((limit or 150) * 0.8) * 100))
            if not v_regionu:
                sk = min(sk, 30)
            odp = f"{nazev_kraje(kn)}, cca {km} km od sídla ({s.get('mesto') or s.get('kraj')}) po silnici"
            if limit and km > limit * 1.3:
                ko.append(f"místo plnění {km} km od sídla (limit {limit} km)")
        else:
            sk = 100 if v_regionu else 60
            odp = f"{nazev_kraje(kn)}, {km} km – u vašeho oboru lze plnit převážně vzdáleně"
        kr.append({"klic": "lokalita", "otazka": "Vyplatí se nám tam jezdit?", "odpoved": odp, "skore": sk, "km": km})
    else:
        kr.append({"klic": "lokalita", "otazka": "Vyplatí se nám tam jezdit?", "odpoved": "místo plnění neuvedeno", "skore": None})

    # 3 velikost
    hod = z.get("predpokladana_hodnota")
    b = profil.get("budget") or {}
    lo, hi = b.get("min_czk"), b.get("max_czk")
    if hod:
        if (lo is None or hod >= lo) and (hi is None or hod <= hi):
            sk = 100
        elif hi and hod > hi:
            sk = max(0, round(100 - (hod / hi - 1) * 60))
            if hod > hi * 3:
                ko.append(f"hodnota {kc(hod)} výrazně nad vaší kapacitou ({kc(hi)})")
        else:
            sk = max(20, round(100 * hod / lo)) if lo else 70
        kr.append({"klic": "velikost", "otazka": "Sedí velikost zakázky na naši kapacitu?",
                   "odpoved": f"{kc(hod)} (váš rozsah {kc(lo) if lo else '0'} – {kc(hi) if hi else 'bez limitu'})", "skore": sk})
    else:
        kr.append({"klic": "velikost", "otazka": "Sedí velikost zakázky na naši kapacitu?", "odpoved": "hodnota neuvedena", "skore": None})

    # 4 cas
    lh = parse_date(z.get("lhuta_nabidek"))
    prep = profil.get("min_prep_days") or 10
    if lh:
        dni = (lh - today).days
        if dni < 0:
            kr.append({"klic": "cas", "otazka": "Stihneme připravit nabídku?", "odpoved": f"lhůta uplynula {lh.isoformat()} (ukázka z historie)", "skore": None, "uplynula": True})
        else:
            sk = 100 if dni >= prep else round(100 * dni / prep)
            if dni < prep * 0.5:
                ko.append(f"na nabídku zbývá jen {dni} dní (potřebujete {prep})")
            kr.append({"klic": "cas", "otazka": "Stihneme připravit nabídku?", "odpoved": f"zbývá {dni} dní do {lh.isoformat()} (potřebujete {prep})", "skore": sk})
    else:
        kr.append({"klic": "cas", "otazka": "Stihneme připravit nabídku?", "odpoved": "lhůta neuvedena", "skore": None})

    # 5 zadavatel
    zi = z.get("zadavatel_ico")
    if zi and zi in (profil.get("blacklist_procurer_icos") or []):
        ko.append("zadavatel je na vašem blacklistu")
        sk, odp = 0, "na blacklistu"
    elif zi and (zi in (profil.get("whitelist_procurer_icos") or []) or zi in klienti):
        sk, odp = 100, "známý zákazník – už jste u něj vyhráli"
    else:
        sk, odp = 55, "nový zadavatel"
    kr.append({"klic": "zadavatel", "otazka": "Známe zadavatele?", "odpoved": f"{z.get('zadavatel_nazev') or '?'} – {odp}", "skore": sk})

    # 6 konkurence
    k = konk.get((z.get("cpv_hlavni") or "")[:2]) or {}
    if k.get("prumer_nabidek") or k.get("top_podil") is not None:
        pn = k.get("prumer_nabidek")
        sk = 50
        if pn:
            sk = round(max(10, min(100, 110 - pn * 12)))
        if k.get("top_podil") and k["top_podil"] > 0.5:
            sk = min(sk, 40)
        odp = (f"v segmentu průměrně {pn:.1f} nabídky" if pn else "počet nabídek neznámý") + \
              (f", největší dodavatel vyhrává {k['top_podil'] * 100:.0f} %" if k.get("top_podil") is not None else "")
        kr.append({"klic": "konkurence", "otazka": "Jak silná je konkurence?", "odpoved": odp, "skore": sk})
    else:
        kr.append({"klic": "konkurence", "otazka": "Jak silná je konkurence?", "odpoved": "málo dat o segmentu", "skore": None})

    # 7 kvalifikace: obrat a reference z verejnych dat + co zadavatel uvadi + profil
    sk7, odp7, ko7 = _kvalifikace(z, profil, kap)
    if ko7:
        ko.append(ko7)
    kr.append({"klic": "kvalifikace", "otazka": "Splníme kvalifikaci (obrat, reference)?", "odpoved": odp7, "skore": sk7, "rucne": True})

    # dealbreakery: negativni slova
    nz = " " + norm(z.get("nazev")) + " "
    for n in profil.get("negative_keywords") or []:
        nn = norm(n)
        if nn and (f" {nn} " in nz or (len(nn) > 6 and nn in nz)):
            ko.append(f"obsahuje vyloučené slovo „{n}“")

    for c in kr:
        c["vaha"] = VAHY[c["klic"]] // (4 if c["klic"] == "lokalita" and not lokalni else 1)
    platne = [c for c in kr if c["skore"] is not None]
    celk = round(sum(c["skore"] * c["vaha"] for c in platne) / sum(c["vaha"] for c in platne)) if platne else 0
    if ko:
        celk = min(celk, 25)
    verdikt = "nevhodné" if ko else "doporučeno" if celk >= 70 else "zvážit" if celk >= 50 else "spíš ne"
    return {"skore": celk, "verdikt": verdikt, "ko": ko, "kriteria": kr}


def zpravodaj(con, profil, today=None, dni=14, limit=30):
    """Backtest: zakazky vyhlasene za poslednich `dni` dni (nebo poslednich dni, ktere open data pokryvaji)."""
    today = today or date.today()
    max_d = con.execute("SELECT MAX(datum_zahajeni) FROM zakazky WHERE datum_zahajeni <= ?", (today.isoformat(),)).fetchone()[0]
    if not max_d:
        return {"od": None, "do": None, "poznamka": "Databáze je prázdná – nejdřív spusťte Data → Rychlá aktualizace.",
                "kandidatu": 0, "polozky": []}
    ref = min(today, date.fromisoformat(max_d[:10]))
    od = ref - timedelta(days=dni)
    pozn = None
    if ref < today - timedelta(days=3):
        pozn = (f"Open data vycházejí jednou měsíčně, nejnovější zakázka v databázi je z {ref.isoformat()}. "
                f"Zpravodaj proto ukazuje posledních {dni} dní, které data pokrývají ({od.isoformat()} – {ref.isoformat()}).")
    # otevrene zakazky (lhuta jeste bezi) + backtest: vyhlasene v okne, a to jen ty, jejichz lhuta nebyla pred oknem
    kand = [dict(r) for r in con.execute(
        """SELECT * FROM zakazky WHERE lhuta_nabidek >= ?
           OR (datum_zahajeni > ? AND datum_zahajeni <= ? AND (lhuta_nabidek IS NULL OR lhuta_nabidek >= ?))""",
        (today.isoformat(), od.isoformat(), ref.isoformat(), od.isoformat()))]
    kand = [z for z in kand if not any(w in norm(z.get("stav")) for w in ("zrus",))]
    tf = TfIdf([text_zakazky(z) for z in kand]) if kand else None
    dotaz = " ".join([profil.get("core_capabilities_description") or ""] + (profil.get("keywords") or [])
                     + [CPV_DIV.get(c[:2], "") for c in profil["cpv_codes"]["main"]])
    qv = tf.vektor(dotaz) if tf else {}
    konk = _konkurence(con)
    kap = kapacita(con, profil["ico"], today)
    klienti = {r[0] for r in con.execute("SELECT DISTINCT z.zadavatel_ico FROM vitezove v JOIN zakazky z ON z.id=v.zakazka_id WHERE v.dodavatel_ico=?", (profil["ico"],))}
    polozky = []
    for z in kand:
        v = vhodnost(z, profil, tf, qv, konk, today, klienti, kap)
        if v["kriteria"][0]["skore"] < 35:  # predmet vubec nesedi -> do zpravodaje nepatri
            continue
        lh = parse_date(z.get("lhuta_nabidek"))
        polozky.append({"id": z["id"], "nazev": z["nazev"], "zadavatel": z["zadavatel_nazev"], "zadavatel_ico": z["zadavatel_ico"],
                        "kraj": z["kraj"], "hodnota": z["predpokladana_hodnota"], "datum": z["datum_zahajeni"],
                        "lhuta": (z.get("lhuta_nabidek") or "")[:10], "otevrena": bool(lh and lh >= today), "url": z["url"],
                        "segment": cpv_group(z["cpv_hlavni"]), **v})
    polozky.sort(key=lambda p: (not p["otevrena"], -p["skore"], p["lhuta"] or ""))
    # tataz zakazka muze byt v datech vickrat (NEN + Vestnik, aktualizace) -> ponechat jen nejlepe hodnoceny zaznam
    videno, unik = set(), []
    for p in polozky:
        k = (norm(p["nazev"])[:120], p["zadavatel_ico"] or norm(p["zadavatel"]))
        if k not in videno:
            videno.add(k)
            unik.append(p)
    polozky = unik  # nejdriv ty, do kterych jde jeste podat
    return {"od": od.isoformat(), "do": ref.isoformat(), "poznamka": pozn, "kandidatu": len(kand),
            "otevrenych": sum(1 for p in polozky if p["otevrena"]),
            "doporuceno": sum(1 for p in polozky if p["verdikt"] == "doporučeno"), "polozky": polozky[:limit]}


def vhodnost_jedne(con, ico, zakazka_id, today=None, vlastnik=""):
    st = nacti(con, ico, vlastnik)
    if not st or not st.get("profil"):
        raise ValueError("Firma nemá dokončený onboarding.")
    profil = st["profil"]
    z = con.execute("SELECT * FROM zakazky WHERE id=?", (zakazka_id,)).fetchone()
    if not z:
        raise ValueError("Zakázka nenalezena")
    z = dict(z)
    vse = [dict(r) for r in con.execute("SELECT nazev, cpv FROM zakazky ORDER BY datum_zahajeni DESC LIMIT 3000")]
    tf = TfIdf([text_zakazky(x) for x in vse])
    qv = tf.vektor(profil.get("core_capabilities_description") or "")
    return vhodnost(z, profil, tf, qv, _konkurence(con), today or date.today(), kap=kapacita(con, profil["ico"], today))
