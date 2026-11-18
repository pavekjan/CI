"""Agentni onboarding a Day-0 zpravodaj.

1. Recon agent      - z IČO (a volitelne webu) potichu sesbira: ARES, historii firmy v databazi zakazek
                      (vyhry, ucasti, CPV, zadavatele, kraje), Registr smluv, volitelne Hlidac statu, text webu.
2. Onboarding agent - Faze 1: hypoteza + 6 cilenych otazek podlozenych daty (CI analyza) s quick_replies (JSON needs_clarification).
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
from .odkazy import odkazy
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
# obecna slova ze smluv a nazvu zakazek, ktera nic nerikaji o oboru (pro klicova slova profilu)
STOP_KW = STOP | set("""dodatek dodatku dodatkem zmena zmeny zmenu cislo cisla plneni terminu termin etapa etapy etape
ramcova ramcove ramcovou dohoda dohody dohodu objednavka objednavky kupni smlouve uzavreni uzavrene castka ceny cena
celkem zaklade ucelem akce akci projekt projektu stavba stavby casti cast lotu cislem ostatni dalsi vcetne mesic
leden unor brezen duben kveten cerven cervenec srpen zari rijen listopad prosinec roku rok""".split())


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


_MODEL = {}


def _model_segmentu(con):
    """Naivni Bayes z ts/segmenty.py (nauceny na zakazkach s CPV), drzi se v pameti podle poctu zakazek."""
    from . import segmenty
    n = con.execute("SELECT COUNT(*) FROM zakazky WHERE LENGTH(cpv_hlavni) >= 8").fetchone()[0]
    if _MODEL.get("n") != n:
        _MODEL.update(n=n, m=segmenty.nauc(con, limit=80000))
    return _MODEL["m"]


def auto_cpv(con, ico, vyhry):
    """CPV kody firmy automaticky z jeji historie, serazene podle vahy:
    - vyhrane zakazky s CPV: 1 bod za vyhru + az 3 body podle podilu na objemu vyher,
    - zakazky, kde firma podala nabidku (i neuspesne): 0,5 bodu,
    - vyhry bez CPV s odhadnutym oborem a smlouvy z Registru smluv (predmet smlouvy zarazeny podle slov): 0,3 bodu
      do oboru (kod XX000000).
    Vraci {"top_cpv": [...], "cpv_zdroj": "popis pro uzivatele"}."""
    body, zdroje = Counter(), defaultdict(Counter)
    objem = sum((v["cena_bez_dph"] or v["predpokladana_hodnota"] or 0) for v in vyhry) or 1
    for v in vyhry:
        c = v["cpv_hlavni"] or ""
        if len(c) >= 8:
            body[c[:8]] += 1 + 3 * (v["cena_bez_dph"] or v["predpokladana_hodnota"] or 0) / objem
            zdroje[c[:8]]["výhry"] += 1
        elif len(c) == 2:
            body[c + "000000"] += 0.3
            zdroje[c + "000000"]["výhry (odhad oboru)"] += 1
    for (c,) in con.execute("""SELECT z.cpv_hlavni FROM ucastnici u JOIN zakazky z ON z.id=u.zakazka_id
                               WHERE u.dodavatel_ico=? AND LENGTH(z.cpv_hlavni) >= 8
                               AND z.id NOT IN (SELECT zakazka_id FROM vitezove WHERE dodavatel_ico=?)""", (ico, ico)):
        body[c[:8]] += 0.5
        zdroje[c[:8]]["nabídky"] += 1
    predmety = [r[0] for r in con.execute("""SELECT s.predmet FROM smlouvy_strany st JOIN smlouvy s ON s.id=st.smlouva_id
                                             WHERE st.ico=? AND s.predmet IS NOT NULL LIMIT 400""", (ico,))]
    n_rs = 0
    if predmety:
        m = _model_segmentu(con)
        for t in predmety:
            oddil, jistota = m.odhad(t, None, None)
            if oddil and jistota >= 0.6:
                body[oddil + "000000"] += 0.3
                zdroje[oddil + "000000"]["smlouvy"] += 1
                n_rs += 1
    # obor jen ze smluv (bez vyher a nabidek) az od 3 smluv - predmety smluv jsou kratke a odhad je mene jisty
    for c in [c for c in body if set(zdroje[c]) == {"smlouvy"} and zdroje[c]["smlouvy"] < 3]:
        del body[c]
    top = [{"cpv": c, "pocet": sum(zdroje[c].values()), "vaha": round(b, 2), "segment": cpv_group(c),
            "zdroj": ", ".join(f"{k} {n}" for k, n in zdroje[c].items())} for c, b in body.most_common(12)]
    n_v = sum(1 for v in vyhry if v["cpv_hlavni"])
    n_u = sum(z.get("nabídky", 0) for z in zdroje.values())
    popis = (f"Obory (kódy CPV) doplněné automaticky z historie firmy: {n_v} vyhraných zakázek, {n_u} podaných nabídek"
             f" a {n_rs} smluv z Registru smluv." if top else "")
    return {"top_cpv": top, "cpv_zdroj": popis}


# Typ zakaznika podle nazvu zadavatele (poradi je dulezite: "Krajska nemocnice" je nemocnice, ne kraj)
TYPY_ZAKAZNIKU = [
    (r"nemocnic|zdravotn|lecebn|zachrann|hygienick|lazen", "nemocnice a zdravotnictví"),
    (r"ministerstvo obrany|vojensk|armad|vojenske", "armáda"),
    (r"policie|hasic|vezensk|soud|statni zastupitelstv|celni", "policie, hasiči, vězeňství a justice"),
    (r"skol|gymnazi|univerzit|vysoke uceni|uciliste|akademie|ustav .* av cr|akademie ved", "školy, univerzity a výzkum"),
    (r"domov|socialn|senior|pecovatel|dusevni", "domovy a sociální služby"),
    (r"doprav|drahy|zeleznic|letiste|silnic|dalnic|rizeni letoveho", "doprava (dráhy, silnice, dopravní podniky)"),
    (r"kraj", "kraje"),
    (r"^mesto|^obec|mestska cast|statutarni|^mestys|magistrat|mestsky urad|obecni urad", "obce a města"),
    (r"ministerstv|urad|statni|sprava|agentura|fond|inspekce|cesky|ceska|narodni", "ministerstva a státní instituce"),
]


def typ_zakaznika(nazev):
    n = norm(nazev or "")
    if not n:
        return None
    for vzor, typ in TYPY_ZAKAZNIKU:
        if re.search(vzor, n):
            return typ
    return "ostatní (firmy státu, muzea, divadla…)"


# Co firma prodava: oddil CPV -> typ (zbozi / sluzby / stavby / IT) pro lidsky popis a vyber otazek
def typ_oddilu(oddil):
    if oddil == "45":
        return "stavby"
    if oddil in ("48", "72"):
        return "it"
    if oddil and oddil < "45":
        return "zbozi"
    return "sluzby"


# co firma prodava ve 4. pade ("prodava hlavne pocitace a kancelarskou techniku")
CO_PRODAVA = {
    "03": "zemědělské a lesnické produkty", "09": "paliva a energie", "14": "suroviny a kovy", "15": "potraviny a nápoje",
    "16": "zemědělské stroje", "18": "oděvy a obuv", "19": "textil, kůži a plasty", "22": "tiskoviny", "24": "chemické výrobky",
    "30": "počítače a kancelářskou techniku", "31": "elektrické stroje a přístroje", "32": "komunikační a audiovizuální techniku",
    "33": "zdravotnické přístroje a léčiva", "34": "dopravní prostředky a díly k nim", "35": "bezpečnostní a obranné vybavení",
    "37": "sportovní potřeby a hudební nástroje", "38": "laboratorní a měřicí přístroje", "39": "nábytek a vybavení",
    "41": "vodu", "42": "průmyslové stroje", "43": "důlní a stavební stroje", "44": "stavební materiál a konstrukce",
    "45": "stavební práce", "48": "software a informační systémy", "50": "opravy a údržbu", "51": "instalace zařízení",
    "55": "stravování a ubytování", "60": "dopravu", "63": "služby v dopravě", "64": "poštovní a telekomunikační služby",
    "65": "energie a vodu", "66": "finanční a pojišťovací služby", "70": "realitní služby", "71": "projekce a inženýrské služby",
    "72": "IT služby", "73": "výzkum a vývoj", "75": "služby pro veřejnou správu", "77": "zahradnické a zemědělské služby",
    "79": "právní, marketingové a personální služby", "80": "vzdělávání a školení", "85": "zdravotní a sociální služby",
    "90": "úklid, odvoz odpadů a péči o životní prostředí", "92": "kulturní a sportovní služby", "98": "ostatní služby",
}


def co_prodava(o):
    return CO_PRODAVA.get(o["oddil"]) or f"„{o['nazev']}“"


SLOVESO = {"zbozi": "prodává státu hlavně", "stavby": "dělá pro stát hlavně", "it": "dodává státu hlavně",
           "sluzby": "poskytuje státu hlavně"}


def identita(rc):
    """Kdo firma je, srozumitelne: co prodava (podle vyhranych soutezi), komu a jaky je to typ dodavatele.
    Jen z dat (soutěze, Registr smluv, ARES), zadny odhad modelu."""
    h = rc["historie"]
    seg = [x for x in h["segmenty"] if x["segment"] != "neuvedeno"]
    celkem = sum(x["pocet"] for x in seg)
    obory = [{"oddil": x["segment"][:2], "nazev": CPV_DIV.get(x["segment"][:2], x["segment"][3:]),
              "podil": x["pocet"] / celkem if celkem else 0, "pocet": x["pocet"]} for x in seg[:3]]
    zdroj = "soutěže"
    if not obory:
        nc = nace_cpv(rc)
        obory = [{"oddil": codes[0][:2], "nazev": popis, "podil": None, "pocet": 0} for popis, codes in nc[:3]]
        zdroj = "ARES" if obory else None
    typ = typ_oddilu(obory[0]["oddil"]) if obory else None
    typy_z = [x["typ"] for x in h.get("typy_zakazniku") or [] if not x["typ"].startswith("ostatní")][:3]
    return {"typ": typ, "obory": obory, "zakaznici": typy_z, "zdroj": zdroj}


def _vyjmenuj(xs):
    xs = [x for x in xs if x]
    return xs[0] if len(xs) == 1 else ", ".join(xs[:-1]) + " a " + xs[-1] if xs else ""


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
    typy = Counter(typ_zakaznika(v["zadavatel_nazev"]) for v in vyhry) + Counter(typ_zakaznika(s["zadavatel_nazev"]) for s in rs)
    typy.pop(None, None)
    return {
        "vyher": len(vyhry), "ucasti": ucasti, "objem_czk": round(sum(v["cena_bez_dph"] or 0 for v in vyhry)),
        "median_zakazky_czk": _median(ceny), "p10_czk": q(0.1), "p25_czk": q(0.25), "p75_czk": q(0.75), "p90_czk": q(0.9), "max_czk": ceny[-1] if ceny else None,
        **auto_cpv(con, ico, vyhry),
        # "neuvedeno" (zakazky bez CPV a bez odhadu) neni obor -> do profilu ani otazek nepatri
        "segmenty": [{"segment": s, "pocet": n} for s, n in seg.most_common(7) if s != "neuvedeno"][:6],
        "top_zadavatele": sorted(({"ico": k, **v} for k, v in zad.items()), key=lambda x: (-x["pocet"], -x["objem"]))[:10],
        "kraje": [{"nuts3": k, "kraj": nazev_kraje(k), "pocet": n} for k, n in kraje.most_common()],
        "typy_zakazniku": [{"typ": k, "pocet": n} for k, n in typy.most_common(5)],
        "nazvy_vyher": [v["nazev"] for v in sorted(vyhry, key=lambda x: x["datum_zahajeni"] or "", reverse=True)[:25]],
        "registr_smluv": {"pocet": len(rs), "objem_czk": round(sum(s["hodnota_bez_dph"] or 0 for s in rs)),
                          "predmety": [s["predmet"] for s in rs[:15]],
                          "top_smluvni_partneri": [{"ico": k[0], "nazev": k[1], "pocet": n} for k, n in rs_zad.most_common(8)]},
        "obdobi_dat": [r for r in con.execute("SELECT MIN(datum_zahajeni), MAX(datum_zahajeni) FROM zakazky").fetchone()],
    }


# ------------------------------------------------------------------ CI analyza (podklad pro otazky)
def _tvar(n, jedna, dve, pet):
    """Cesky plural: 1 zakazka, 2 zakazky, 5 zakazek."""
    return f"{n} " + (jedna if n == 1 else dve if 2 <= n <= 4 else pet)


def _bez_tecky(t):
    return (t or "").rstrip(".")


def _je_ico(x):
    return bool(x) and bool(re.fullmatch(r"\d{8}", str(x)))


def _ci(con, ico, hist):
    """Konkurencni zpravodajstvi z dat (zadne odhady modelu): souboje s konkurenty, lidri segmentu,
    koncentrace zakazniku, bila mista u stavajicich zakazniku a dynamika. Kazde zjisteni nese zdroj a jistotu."""
    from .api import _nazvy, trh_segmenty
    out = {"souboje": [], "lidri": [], "koncentrace": None, "bila_mista": [], "trend": None, "zjisteni": []}
    moje = {r[0] for r in con.execute("SELECT zakazka_id FROM vitezove WHERE dodavatel_ico=?", (ico,))}
    vse = moje | {r[0] for r in con.execute("SELECT zakazka_id FROM ucastnici WHERE dodavatel_ico=?", (ico,))}

    # 1) prime souboje: kdo se objevil ve stejnych soutezich (jako ucastnik nebo vitez)
    if vse:
        con.execute("CREATE TEMP TABLE IF NOT EXISTS t_ci (id TEXT PRIMARY KEY)")
        con.execute("DELETE FROM t_ci")
        con.executemany("INSERT OR IGNORE INTO t_ci VALUES (?)", [(i,) for i in vse])
        vitez = defaultdict(set)
        for zid, d in con.execute("SELECT zakazka_id, dodavatel_ico FROM vitezove WHERE zakazka_id IN (SELECT id FROM t_ci)"):
            vitez[zid].add(d)
        jini = defaultdict(set)
        for tab in ("ucastnici", "vitezove"):
            # bezpecnost: nazev tabulky je pevna konstanta z kodu, ne vstup
            for zid, d in con.execute(f"SELECT zakazka_id, dodavatel_ico FROM {tab} WHERE zakazka_id IN (SELECT id FROM t_ci)"):  # nosec B608
                if _je_ico(d) and d != ico:
                    jini[zid].add(d)
        h2h = defaultdict(lambda: [0, 0, 0])  # stretu, my vyhra, oni vyhra
        for zid, os_ in jini.items():
            for o in os_:
                h2h[o][0] += 1
                h2h[o][1] += ico in vitez[zid]
                h2h[o][2] += o in vitez[zid]
        top = sorted(h2h.items(), key=lambda kv: (-kv[1][0], -kv[1][2]))[:8]
        nazvy = _nazvy(con, [k for k, _ in top])
        out["souboje"] = [{"ico": k, "nazev": nazvy.get(k) or k, "stretu": v[0], "my_vyhra": v[1], "oni_vyhra": v[2]}
                          for k, v in top if v[0] >= 1]

    # 2) lidri hlavnich segmentu (i kdyz se s firmou primo nepotkali)
    seg = [x["segment"] for x in hist["segmenty"][:2]]
    ts_ = trh_segmenty(con)["seg"]
    lid = defaultdict(lambda: [0.0, 0, None])
    for g in seg:
        for k, v, n in (ts_.get(g) or {}).get("top", [])[:10]:
            if _je_ico(k) and k != ico:
                lid[k][0] += v
                lid[k][1] += n
                lid[k][2] = lid[k][2] or g
    top_l = sorted(lid.items(), key=lambda kv: -kv[1][0])[:6]
    nazvy = _nazvy(con, [k for k, _ in top_l])
    out["lidri"] = [{"ico": k, "nazev": nazvy.get(k) or k, "objem": v[0], "vyhry": v[1], "segment": v[2]} for k, v in top_l]

    # 3) koncentrace zakazniku: vyhry v soutezich + odberatele z Registru smluv
    obj = defaultdict(float)
    nazvy_z = {}
    for zi, zn, c in con.execute("""SELECT z.zadavatel_ico, z.zadavatel_nazev, v.cena_bez_dph FROM vitezove v
                                    JOIN zakazky z ON z.id=v.zakazka_id WHERE v.dodavatel_ico=?""", (ico,)):
        if zi:
            obj[zi] += c or 0
            nazvy_z.setdefault(zi, zn)
    for zi, h in con.execute("SELECT zadavatel_ico, SUM(hodnota) FROM smlouvy_odberatele WHERE ico=? GROUP BY zadavatel_ico", (ico,)):
        if zi:
            obj[zi] += h or 0
    tot = sum(obj.values())
    if obj and tot > 0:
        poradi = sorted(obj.items(), key=lambda kv: -kv[1])
        chybi = [k for k, _ in poradi[:3] if not nazvy_z.get(k)]
        if chybi:
            for r in con.execute(f"SELECT ico, nazev FROM subjekty WHERE ico IN ({','.join('?' * len(chybi))})", chybi):  # nosec B608
                nazvy_z[r[0]] = r[1]
        podil = poradi[0][1] / tot
        hhi = sum((v / tot) ** 2 for v in obj.values())
        out["koncentrace"] = {"zakazniku": len(obj), "top_ico": poradi[0][0], "top_nazev": nazvy_z.get(poradi[0][0]) or poradi[0][0],
                              "top_podil": podil, "top3_podil": sum(v for _, v in poradi[:3]) / tot, "hhi": hhi}

    # 4) bila mista: segmenty, ktere nakupuji vasi zakaznici a kde u nich vyhravaji vasi konkurenti, ale vy ne
    #    (konkurent = primy soupeř, jinak lidr vaseho segmentu). Tim jde o skutecne "sousedni" obory, ne o cokoli,
    #    co velky zakaznik koupi (armada, nemocnice...).
    klienti = [k for k, _ in sorted(obj.items(), key=lambda kv: -kv[1])[:25]]
    rivalove = [x["ico"] for x in out["souboje"]] + [x["ico"] for x in out["lidri"]]
    if klienti and rivalove:
        moje_seg = {x["segment"] for x in hist["segmenty"]}
        bm = defaultdict(lambda: {"objem": 0.0, "pocet": 0, "zakazniku": set(), "vitez": Counter()})
        od = (date.today() - timedelta(days=3 * 365)).isoformat()
        for cpv, zi, d, c in con.execute(
                f"""SELECT z.cpv_hlavni, z.zadavatel_ico, v.dodavatel_ico, v.cena_bez_dph FROM vitezove v JOIN zakazky z ON z.id=v.zakazka_id
                    WHERE v.dodavatel_ico IN ({','.join('?' * len(rivalove))})
                      AND z.zadavatel_ico IN ({','.join('?' * len(klienti))}) AND z.datum_zahajeni >= ?""",  # nosec B608 - jen otazniky
                rivalove + klienti + [od]):
            g = cpv_group(cpv)
            if g in moje_seg or g == "neuvedeno" or not (c and c > 0):
                continue
            b = bm[g]
            b["objem"] += c
            b["pocet"] += 1
            b["zakazniku"].add(zi)
            b["vitez"][d] += c
        # aspon 2 zakazky, poradi podle poctu zakazniku a objemu
        nej = sorted(((g, b) for g, b in bm.items() if b["pocet"] >= 2),
                     key=lambda kv: (-len(kv[1]["zakazniku"]), -kv[1]["objem"]))[:5]
        nazvy = _nazvy(con, [b["vitez"].most_common(1)[0][0] for _, b in nej])
        out["bila_mista"] = [{"segment": g, "objem": b["objem"], "pocet": b["pocet"], "zakazniku": len(b["zakazniku"]),
                              "lidr": nazvy.get(b["vitez"].most_common(1)[0][0])} for g, b in nej]

    # 5) dynamika vyher: poslednich 12 mesicu dat vs. predchozich 12
    max_d = con.execute("SELECT MAX(datum_zahajeni) FROM zakazky WHERE datum_zahajeni <= ?", (date.today().isoformat(),)).fetchone()[0]
    if max_d and moje:
        ref = date.fromisoformat(max_d[:10])
        a, b = (ref - timedelta(days=365)).isoformat(), (ref - timedelta(days=730)).isoformat()
        r = con.execute("""SELECT SUM(z.datum_zahajeni > ?), SUM(z.datum_zahajeni > ? AND z.datum_zahajeni <= ?)
                           FROM vitezove v JOIN zakazky z ON z.id=v.zakazka_id WHERE v.dodavatel_ico=?""", (a, b, a, ico)).fetchone()
        t = con.execute("""SELECT SUM(z.datum_zahajeni > ?), SUM(z.datum_zahajeni > ? AND z.datum_zahajeni <= ?)
                           FROM vitezove v JOIN zakazky z ON z.id=v.zakazka_id WHERE z.datum_zahajeni > ?""", (a, b, a, b)).fetchone()
        # u nejnovejsich soutezi jeste neni znam vitez -> firma se porovnava s vyvojem celeho trhu
        out["trend"] = {"posl12": r[0] or 0, "pred12": r[1] or 0, "do": ref.isoformat(),
                        "trh": ((t[0] or 0) / t[1]) if t and t[1] else 1.0}

    # 6) klicova zjisteni (zdroj + hodnoceni duveryhodnosti podle Admiralty kodu + jistota zaveru)
    zj = out["zjisteni"]
    n_s = len(out["souboje"])
    if out["souboje"]:
        s0 = out["souboje"][0]
        zj.append({"text": f"Nejčastější přímý soupeř: {s0['nazev']} – potkali jste se " + ("v 1 soutěži" if s0["stretu"] == 1 else f"v {s0['stretu']} soutěžích") + ", "
                           f"vy jste vyhráli {s0['my_vyhra']}×, oni {s0['oni_vyhra']}×.",
                   "zdroj": "ISVZ (účastníci soutěží)", "rating": "A1", "jistota": "vysoká" if s0["stretu"] >= 3 else "střední"})
    elif vse:
        zj.append({"text": "U vašich soutěží zdroj neuvádí ostatní účastníky – přímé souboje zatím nelze určit, "
                           "konkurenty odvozuji od největších firem ve vašem oboru.", "zdroj": "ISVZ", "rating": "A1", "jistota": "nízká"})
    k = out["koncentrace"]
    if k and k["zakazniku"] >= 2:
        zj.append({"text": f"Největší zákazník {k['top_nazev']} tvoří {k['top_podil'] * 100:.0f} % vašich veřejných tržeb "
                           f"(top 3 = {k['top3_podil'] * 100:.0f} %, celkem {k['zakazniku']} zákazníků)"
                           + (" – vysoká závislost na jednom odběrateli." if k["top_podil"] >= 0.4 else "."),
                   "zdroj": "ISVZ + Registr smluv", "rating": "A1", "jistota": "vysoká"})
    if out["bila_mista"]:
        b0 = out["bila_mista"][0]
        zj.append({"text": f"Bílé místo: u {_tvar(b0['zakazniku'], 'vašeho zákazníka', 'vašich zákazníků', 'vašich zákazníků')} vyhrávají "
                           f"vaši konkurenti i v oboru {b0['segment'].split(' ', 1)[-1].lower()} ({_tvar(b0['pocet'], 'zakázka', 'zakázky', 'zakázek')} "
                           f"za {kc(b0['objem'])} za 3 roky" + (f", hlavně {b0['lidr']}" if b0["lidr"] else "")
                           + ") – vy tam zatím nedodáváte.",
                   "zdroj": "ISVZ (vítězové u vašich zákazníků)", "rating": "A1", "jistota": "střední"})
    t = out["trend"]
    if t and (t["posl12"] or t["pred12"]):
        rel = ((t["posl12"] + 1) / (t["pred12"] + 1)) / (t.get("trh") or 1.0)
        zm = "rostou rychleji než trh" if rel > 1.2 else "klesají víc než trh" if rel < 0.8 else "se vyvíjejí podobně jako trh"
        zj.append({"text": f"Vaše výhry {zm}: {t['posl12']} za posledních 12 měsíců dat vs. {t['pred12']} v předchozích 12 "
                           f"(celý trh {(t.get('trh', 1.0) - 1) * 100:+.0f} %).",
                   "zdroj": "ISVZ", "rating": "A1", "jistota": "střední" if t["posl12"] + t["pred12"] >= 5 else "nízká"})
    out["souboje_n"] = n_s
    out["porter"] = _porter(con, ico, hist, out)
    return out


def _porter(con, ico, hist, ci):
    """Porterovych pet sil pro hlavni obor firmy, jen z dat verejnych zakazek (posledni rok dat).
    Co z verejnych zakazek zmerit nejde (sila dodavatelu firmy, substituty), je oznacene jako uvaha k doplneni,
    ne jako zjisteni - v CI se fakta a odhady nesmi michat."""
    seg = [x for x in hist["segmenty"] if x["segment"] != "neuvedeno"]
    if not seg:
        return None
    oddil = seg[0]["segment"][:2]
    obor = CPV_DIV.get(oddil, oddil)
    from .api import _cached
    t = _cached(con, f"porter:{oddil}", lambda: _trh_oboru(con, oddil))
    if not t:
        return None
    zak_n, prumer_nab, jedna, jen_cena, cr5, cr5_zad, vitezu, novi_n, novi_podil, max_d = (
        t["zakazek"], t["prumer_nab"], t["jedna"], t["jen_cena"], t["cr5"], t["cr5_zad"], t["vitezu"], t["novi"], t["novi_podil"], t["do"])
    cislo = lambda n: f"{n:,}".replace(",", "\u00a0")  # noqa: E731
    pct = lambda x: f"{x * 100:.0f} %"  # noqa: E731
    sily = []

    # 1) rivalita mezi konkurenty
    if prumer_nab is not None or cr5 is not None:
        vys = (prumer_nab or 0) >= 3.5 or (cr5 is not None and cr5 < 0.25)
        niz = (prumer_nab is not None and prumer_nab < 2) or (cr5 is not None and cr5 > 0.6)
        txt = [f"Za poslední rok dat {cislo(zak_n)} soutěží, vyhrálo je {cislo(vitezu)} různých firem"]
        if prumer_nab is not None:
            txt.append(f"průměrně {prumer_nab:.1f}".replace(".", ",") + " nabídky na soutěž" + (f", {pct(jedna)} soutěží mělo jedinou nabídku" if jedna else ""))
        if cr5 is not None:
            txt.append(f"pět největších dodavatelů má {pct(cr5)} objemu")
        sily.append({"sila": "Rivalita mezi konkurenty", "hodnoceni": "vysoká" if vys else "nízká" if niz else "střední",
                     "text": "; ".join(txt) + ".", "zdroj": "ISVZ", "jistota": "vysoká" if zak_n >= 100 else "střední"})
    # 2) vyjednavaci sila odberatelu (zadavatelu)
    k = ci.get("koncentrace") or {}
    if jen_cena is not None or cr5_zad is not None:
        vys = (jen_cena or 0) >= 0.8 or (k.get("top_podil") or 0) >= 0.4
        niz = (jen_cena is not None and jen_cena < 0.4) and (k.get("top_podil") or 0) < 0.2
        txt = []
        if jen_cena is not None:
            txt.append(f"v {pct(jen_cena)} soutěží rozhoduje jen cena")
        if cr5_zad is not None:
            txt.append(f"pět největších zadavatelů nakupuje {pct(cr5_zad)} objemu oboru")
        if k.get("top_podil"):
            txt.append(f"váš největší zákazník vám dává {pct(k['top_podil'])} tržeb od státu")
        sily.append({"sila": "Síla odběratelů (zadavatelů)", "hodnoceni": "vysoká" if vys else "nízká" if niz else "střední",
                     "text": ("; ".join(txt) + ".")[:1].upper() + ("; ".join(txt) + ".")[1:], "zdroj": "ISVZ + Registr smluv", "jistota": "střední"})
    # 3) hrozba novych konkurentu
    if novi_podil is not None:
        sily.append({"sila": "Hrozba nových konkurentů", "hodnoceni": "vysoká" if novi_podil >= 0.3 else "nízká" if novi_podil < 0.1 else "střední",
                     "text": f"Nováčci (předchozí 2 roky v oboru nevyhráli): {cislo(novi_n)} z {cislo(vitezu)} vítězných firem, dohromady {pct(novi_podil)} objemu.",
                     "zdroj": "ISVZ", "jistota": "střední"})
    # 4-5) co z verejnych dat zjistit nejde - uvaha pro uzivatele, ne zjisteni
    sily.append({"sila": "Hrozba náhražek (substitutů)", "hodnoceni": "posuďte sami",
                 "text": "Z veřejných zakázek se nedá změřit. Zvažte, zda úřady mohou totéž řešit jinak: vlastními silami, "
                         "centrálním nákupem, pronájmem místo koupě nebo jinou technologií.", "zdroj": "úvaha", "jistota": "–"})
    sily.append({"sila": "Síla vašich dodavatelů", "hodnoceni": "posuďte sami",
                 "text": "Z veřejných dat nejde zjistit, od koho nakupujete vy. Pokud máte jednoho klíčového výrobce nebo dovozce, "
                         "může vám zdražit nebo dodávky omezit a tím ohrozit i vaše nabídky.", "zdroj": "úvaha", "jistota": "–"})
    return {"obor": obor, "obdobi_do": max_d[:10], "sily": sily}


def _trh_oboru(con, oddil):
    """Souhrn oboru (oddil CPV) za posledni rok dat - spolecny pro vsechny firmy, proto v cache."""
    max_d = con.execute("SELECT MAX(datum_zahajeni) FROM zakazky WHERE datum_zahajeni <= ?", (date.today().isoformat(),)).fetchone()[0]
    if not max_d:
        return None
    ref = date.fromisoformat(max_d[:10])
    rok, tri = (ref - timedelta(days=365)).isoformat(), (ref - timedelta(days=3 * 365)).isoformat()
    zak = con.execute("""SELECT pocet_nabidek, kriteria FROM zakazky
                         WHERE datum_zahajeni > ? AND datum_zahajeni <= ? AND cpv_hlavni LIKE ?""", (rok, max_d, oddil + "%")).fetchall()
    if len(zak) < 20:
        return None
    nab = [r[0] for r in zak if r[0]]
    krit = [norm(r[1]) for r in zak if r[1]]
    vit, zad, drive = defaultdict(float), defaultdict(float), set()
    for d, zi, c, dz in con.execute("""SELECT v.dodavatel_ico, z.zadavatel_ico, COALESCE(v.cena_bez_dph, 0), z.datum_zahajeni
                                       FROM vitezove v JOIN zakazky z ON z.id=v.zakazka_id
                                       WHERE z.datum_zahajeni > ? AND z.datum_zahajeni <= ? AND z.cpv_hlavni LIKE ?""",
                                    (tri, max_d, oddil + "%")):
        if dz <= rok:
            drive.add(d)
            continue
        if _je_ico(d):
            vit[d] += c or 0
        if zi:
            zad[zi] += c or 0
    tot_v, tot_z = sum(vit.values()), sum(zad.values())
    novi = [d for d in vit if d not in drive]
    return {"zakazek": len(zak), "do": max_d[:10],
            "prumer_nab": sum(nab) / len(nab) if nab else None,
            "jedna": sum(1 for x in nab if x == 1) / len(nab) if nab else None,
            "jen_cena": sum(1 for k in krit if "cena" in k and "kvalit" not in k) / len(krit) if len(krit) >= 10 else None,
            "cr5": sum(sorted(vit.values(), reverse=True)[:5]) / tot_v if tot_v else None,
            "cr5_zad": sum(sorted(zad.values(), reverse=True)[:5]) / tot_z if tot_z else None,
            "vitezu": len(vit), "novi": len(novi), "novi_podil": sum(vit[d] for d in novi) / tot_v if tot_v else None}


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
        ci = _ci(con, ico, hist)
        web = f_web.result() if f_web else None
        hlidac = f_hl.result() if f_hl else None
    nazev = (ares or {}).get("nazev") or (con.execute("SELECT nazev FROM dodavatele WHERE ico=?", (ico,)).fetchone() or [None])[0]
    zdroje = [{"id": "ARES", "nazev": "ARES – ekonomické subjekty", "url": f"https://ares.gov.cz/ekonomicke-subjekty?ico={ico}", "rating": "A1", "ok": bool(ares)},
              {"id": "RVZ", "nazev": "Registr veřejných zakázek (ISVZ)", "url": "https://isvz.nipez.cz/", "rating": "A1", "ok": hist["vyher"] + hist["ucasti"] > 0},
              {"id": "RS", "nazev": "Registr smluv", "url": "https://smlouvy.gov.cz/", "rating": "A1", "ok": hist["registr_smluv"]["pocet"] > 0}]
    if hlidac is not None:
        zdroje.append({"id": "HS", "nazev": "Hlídač státu – smlouvy (3 roky)", "url": f"https://www.hlidacstatu.cz/subjekt/{ico}", "rating": "B2", "ok": "chyba" not in hlidac})
    if web is not None:
        zdroje.append({"id": "WEB", "nazev": "Web firmy", "url": web.get("url"), "rating": "C3", "ok": "chyba" not in web})
    log(A, f"Recon {ico}: {nazev} – {hist['vyher']} výher, {hist['registr_smluv']['pocet']} smluv RS ({(datetime.now() - t0).total_seconds():.1f} s)")
    out = {"ico": ico, "nazev": nazev or ico, "ares": ares, "sidlo": sidlo_firmy(ares), "historie": hist,
           "hlidac_statu": hlidac, "web": web, "zdroje": zdroje, "ci": ci}
    out["identita"] = identita(out)
    return out


# ------------------------------------------------------------------ vertikala
VERT_CPV = {"45": "stavebnictvi", "44": "stavebnictvi", "43": "stavebnictvi", "71": "stavebnictvi",
            "72": "it_sw", "48": "it_sw",  # 30/32 (pocitace, elektronika) = dodavky zbozi, ne IT sluzby
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
    "4322": ("Instalatérské práce, topení, klimatizace a vzduchotechnika", ["45331000", "45331220", "45332000", "45330000", "42512000", "50730000"]),
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


# slova, podle kterych se pozna zakazka pro danou cinnost (pro firmy bez historie: textova shoda se zakazkami)
NACE_SLOVA = {
    "4322": ["klimatizace", "vzduchotechnika", "topení", "vytápění", "tepelné čerpadlo", "zdravotechnika", "rozvody vody", "kotelna"],
    "4321": ["elektroinstalace", "rozvody", "osvětlení", "hromosvod", "revize elektro"],
    "4120": ["rekonstrukce budovy", "stavební úpravy", "novostavba", "přístavba"],
    "4211": ["silnice", "chodník", "komunikace", "parkoviště"], "4221": ["vodovod", "kanalizace", "čistírna"],
    "4391": ["střecha", "střešní plášť", "klempířské"], "4332": ["okna", "dveře", "truhlářské"], "4334": ["malování", "nátěry"],
    "8121": ["úklid", "úklidové služby", "čištění"], "8122": ["mytí oken", "čištění fasád", "dezinfekce"],
    "8129": ["deratizace", "dezinsekce", "dezinfekce", "čištění komunikací"], "8130": ["údržba zeleně", "sečení", "kácení"],
    "8010": ["ostraha", "bezpečnostní služby", "recepce"], "6201": ["vývoj software", "aplikace", "informační systém"],
    "5610": ["stravování", "catering", "jídelna"], "3811": ["svoz odpadu", "odpady"],
}


def nace_cpv(rc):
    """[(popis, [cpv...]), ...] podle NACE z ARES. ARES cinnosti neradi podle dulezitosti, proto se nahoru dava
    cinnost, ktera odpovida nazvu firmy (EM - Instalace -> instalace), pak presnejsi (5mistne) kody."""
    out, kody = [], []
    for n in ((rc.get("ares") or {}).get("nace") or "").split(","):
        n = n.strip()
        hit = NACE_CPV.get(n[:4]) if len(n) >= 4 else None  # 2-3mistny kod je moc obecny
        if hit and hit not in out:
            out.append(hit)
            kody.append(n[:4])
    jmeno = [w[:5] for w in norm(rc.get("nazev") or "").split() if len(w) >= 5]
    def skore(i):
        slova = norm(out[i][0] + " " + " ".join(NACE_SLOVA.get(kody[i], [])))
        return -sum(1 for w in jmeno if w in slova)
    poradi = sorted(range(len(out)), key=lambda i: (skore(i), i))
    return [out[i] for i in poradi]


def nace_slova(rc, popisy):
    """Klicova slova k vybranym cinnostem (podle popisu z nace_cpv)."""
    kod = {v[0]: k for k, v in NACE_CPV.items()}
    return [w for p in popisy for w in NACE_SLOVA.get(kod.get(p), [])]


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
SPOLEC = "Půjdeme i se společníkem / subdodavatelem"
# Co zadavatele chteji u remesel (firmy bez historie poznane podle cinnosti v ARES)
KVAL_NACE = {
    "4322": ["Certifikát pro práci s chladivy (F-plyny)", "Oprávnění na plynová zařízení", "Revizní technik",
             "Reference z veřejných budov (školy, úřady)", "ISO 9001", SPOLEC],
    "4321": ["Odborná způsobilost v elektrotechnice", "Revizní technik elektro", "Reference z veřejných budov",
             "ISO 9001", SPOLEC],
    "8121": ["Náhradní plnění (chráněný trh práce)", "Pojištění odpovědnosti", "Reference u nemocnic / úřadů", "ISO 9001", SPOLEC],
    "8129": ["Odborná způsobilost pro deratizaci a dezinsekci", "Pojištění odpovědnosti", "Reference u nemocnic / úřadů",
             "ISO 9001", SPOLEC],
}
# Co zadavatele u dodavek zbozi typicky chteji, podle toho, co firma prodava (oddil CPV)
KVAL_ZBOZI = {
    "15": ["Kontrola kvality potravin (HACCP, IFS)", "Vlastní chlazená doprava", "Dodávky každý den, i o víkendu",
           "Bio, regionální nebo dietní potraviny", "Reference u nemocnic, škol nebo armády", SPOLEC],
    "30": ["Autorizovaný prodejce výrobců (HP, Dell, Lenovo…)", "Vlastní servis a záruční opravy", "Dodání do 48 hodin",
           "Zpětný odběr a ekologická likvidace", "Reference ve veřejné správě", SPOLEC],
    "32": ["Autorizovaný prodejce výrobců", "Vlastní servis a záruční opravy", "Montáž a zapojení u zákazníka",
           "Zpětný odběr a ekologická likvidace", "Reference ve veřejné správě", SPOLEC],
    "33": ["Povolení k distribuci léčiv nebo zdravotnických prostředků (SÚKL)", "Vlastní servis přístrojů",
           "Školení personálu k přístrojům", "Reference u nemocnic", SPOLEC],
    "34": ["Jsme výrobce nebo jeho autorizovaný zástupce", "Vlastní servis a náhradní díly", "Schválení vozidel / homologace",
           "ISO 9001", "Reference u dopravců a úřadů", SPOLEC],
    "09": ["Licence na obchod s energií nebo palivy", "Vlastní síť čerpacích stanic", "Palivové karty pro vozový park",
           "Reference ve veřejné správě", SPOLEC],
    "39": ["Vlastní výroba nábytku nebo vybavení", "Montáž u zákazníka", "Certifikáty bezpečnosti a ekologie (FSC, Ekoznačka)",
           "Reference ve veřejné správě", SPOLEC],
    None: ["Autorizovaný prodejce výrobce", "Vlastní servis", "ISO 9001", "Reference ve veřejné správě", SPOLEC],
}


def _od(h):
    """Spodni hranice beznych zakazek firmy (10. percentil) - stejne cislo v dukazu i v moznosti "Jako dosud"."""
    x = h.get("p10_czk") or h.get("p25_czk")
    return None if x is None else float(round(x, -3) if x < 1e6 else round(x, -5))


def _do(h):
    x = h.get("p90_czk") or h.get("p75_czk")
    return None if x is None else float(round(x, -3) if x < 1e6 else round(x, -5))


def faze1_pravidla(rc):
    h, s = rc["historie"], rc["sidlo"]
    vert = urci_vertikalu(rc)
    lokalni = vert in LOKALNI_VERTIKALY
    seg = [x["segment"] for x in h["segmenty"][:3]]
    idn = rc.get("identita") or identita(rc)
    misto = s.get("mesto") or s.get("kraj")
    shr = f"{rc['nazev']}" + (f" ({misto})" if misto else "") + " "
    ob = idn["obory"]
    if ob and idn["zdroj"] == "soutěže":
        o0 = ob[0]
        shr += (f"{SLOVESO[idn['typ']]} {co_prodava(o0)} – to je {o0['podil'] * 100:.0f} % z "
                f"{_tvar(h['vyher'], 'vyhrané soutěže', 'vyhraných soutěží', 'vyhraných soutěží')}")
        dalsi = [co_prodava(o) for o in ob[1:] if o["podil"] >= 0.03]
        shr += (f", dále {_vyjmenuj(dalsi)}. " if dalsi else ". ")
        if idn["zakaznici"]:
            shr += f"Nejčastější zákazníci: {'; '.join(idn['zakaznici'])}. "
        shr += (f"Vyhrané zakázky celkem za {kc(h['objem_czk'])}, typická zakázka kolem {kc(h['median_zakazky_czk'])}. "
                if h["median_zakazky_czk"] else "")
    elif ob:
        shr += (f"– ve veřejných zakázkách zatím žádnou výhru nevidím. Podle živností zapsaných v ARES jde hlavně o: "
                f"{'; '.join(o['nazev'].lower() for o in ob)}. ")
    else:
        shr += "– ve veřejných zakázkách zatím žádnou výhru nevidím a z rejstříků nepoznám, co firma dělá. Napište to prosím do první otázky. "
    if h["registr_smluv"]["pocet"]:
        shr += (f"V Registru smluv (smlouvy s úřady nad 50 tis. Kč) je {_tvar(h['registr_smluv']['pocet'], 'smlouvu', 'smlouvy', 'smluv')}"
                + (f" za {kc(h['registr_smluv']['objem_czk'])}" if h["registr_smluv"]["objem_czk"] else "") + ".")

    q1 = [x["segment"].split(" ", 1)[-1] for x in h["segmenty"][:3] if x["segment"] != "neuvedeno"] or [p for p, _ in nace_cpv(rc)[:3]] or {
        "stavebnictvi": ["Pozemní stavby", "Silnice a komunikace", "Vodovody a kanalizace"],
        "it_sw": ["Vývoj software na zakázku", "Provoz a podpora IS", "Licence a cloud"],
        "facility_sluzby": ["Úklid", "Údržba budov", "Ostraha"],
        "dodavky_zbozi": ["Dodávky techniky", "Spotřební materiál", "Vybavení"],
        "poradenstvi": ["Právní a ekonomické poradenství", "Dotační management", "Školení"], "jine": ["Hlavní činnost firmy"]}[vert]
    # "Nechceme" jen u oboru, ktery mezi nabizenymi neni (Siemens nema dostat "Stavební práce" i "Nechceme: stavební práce")
    nabidnute = {norm(x) for x in q1}
    neg1 = [n for n in VERT_NEG[vert] if norm(n) not in nabidnute and not any(norm(n) in x or x in norm(n) for x in nabidnute)]
    bez_historie = not [x for x in h["segmenty"] if x["segment"] != "neuvedeno"]
    if bez_historie:
        q1 = [p for p, _ in nace_cpv(rc)[:5]] or q1  # u firmy bez zakazek nejdriv zjistit, co vubec dela
    else:
        q1 = q1 + [f"Nechceme: {neg1[0]}"] if neg1 else q1

    med = h["median_zakazky_czk"]
    q2 = ["Malé zakázky do 6 mil. Kč" if vert == "stavebnictvi" else "Malé zakázky do 2 mil. Kč", "2–10 mil. Kč", "10–50 mil. Kč", "nad 50 mil. Kč"]
    if med:
        q2.insert(0, f"Jako dosud: {kc(_od(h))} – {kc(_do(h))}")
    q2 = q2[:5]
    q_prep = ["Stačí nám 5 dní", "Aspoň 10 dní", "Aspoň 15 dní", "Aspoň 20 dní"]

    if lokalni:
        q3 = [f"Jen {s['kraj']}" if s.get("kraj") else "Jen kraj sídla", "Kraj sídla + sousední kraje", "Do 100 km od sídla", "Celá ČR"]
        top_k = [k["kraj"] for k in h["kraje"][:2] if k["nuts3"] != s.get("nuts3")]
        if top_k:
            q3.insert(2, "Jako dosud: " + ", ".join([s.get("kraj") or ""] + top_k).strip(", "))
        q3_text = "Jak daleko od sídla jste ochotni zakázky dělat?"
        q3_cat = "Kde chcete pracovat"
    elif vert == "dodavky_zbozi":
        q3 = ["Dovezeme kamkoli v Česku", f"Jen {s['kraj']} a sousední kraje" if s.get("kraj") else "Jen náš kraj a sousední kraje",
              "Do 100 km od sídla nebo skladu"]
        top_k = [k["kraj"] for k in h["kraje"][:3]]
        if top_k:
            q3.insert(1, "Jako dosud: " + ", ".join(top_k))
        q3_text = "Kam jste schopni zboží dovézt?"
        q3_cat = "Kam dodáváte"
    else:
        q3 = ["Dodáme hotové řešení na klíč", "Pronajímáme své lidi (bodyshopping)", "Obojí", "Kdekoli v ČR, na místě jen výjimečně"]
        q3_text = "Jak zakázky obvykle dodáváte?"
        q3_cat = "Jak dodáváte"

    q4 = {"stavebnictvi": ["Autorizace ČKAIT", "Stavbyvedoucí s praxí 5+ let", "ISO 9001 / 14001 / 45001", "Reference nad 10 mil. Kč", "Půjdeme i se společníkem / subdodavatelem"],
          "it_sw": ["ISO 27001", "Prověrka NBÚ", "Reference ve veřejné správě", "Certifikace výrobců (Microsoft, SAP, Cisco…)", "Půjdeme i se společníkem / subdodavatelem"],
          "facility_sluzby": ["Náhradní plnění (chráněný trh práce)", "ISO 9001", "Pojištění odpovědnosti 10+ mil. Kč", "Reference u nemocnic / úřadů", "Půjdeme i se společníkem / subdodavatelem"],
          "dodavky_zbozi": KVAL_ZBOZI.get((idn["obory"] or [{}])[0].get("oddil"), KVAL_ZBOZI[None]),
          "poradenstvi": ["Odborná způsobilost / autorizace", "Reference ve veřejné správě", "ISO 9001", "Klíčoví experti s praxí 5+ let", "Půjdeme i se společníkem / subdodavatelem"],
          "jine": ["ISO 9001", "Reference ve veřejné správě", "Půjdeme i se společníkem / subdodavatelem"]}[vert]
    if bez_historie:
        kod = {v[0]: k for k, v in NACE_CPV.items()}.get((nace_cpv(rc) or [("", [])])[0][0])
        q4 = KVAL_NACE.get(kod, q4)
        q2 = ["Do 500 tis. Kč", "0,5–2 mil. Kč", "2–10 mil. Kč", "10–50 mil. Kč", "nad 50 mil. Kč"]

    ci = rc.get("ci") or {}
    seg_ev = [f"{x['segment']}: {x['pocet']} " + ("výhra" if x["pocet"] == 1 else "výhry" if x["pocet"] < 5 else "výher")
              for x in h["segmenty"][:3]]
    ev1 = ([{"text": "V čem jste dosud vyhrávali: " + "; ".join(x.split(" ", 1)[-1] for x in seg_ev), "zdroj": "ISVZ", "rating": "A1"}] if seg_ev else
           [{"text": "Ve veřejných zakázkách zatím nemáte žádnou výhru, proto nevím jistě, co děláte. Nabízím činnosti, "
                     "které máte zapsané v ARES (firmy jich mívají zapsaných víc, než opravdu dělají).", "zdroj": "ARES", "rating": "A1"}])
    neg_n = {norm(n) for n in VERT_NEG[vert]}
    for b in [b for b in (ci.get("bila_mista") or []) if norm(b["segment"].split(" ", 1)[-1]) not in neg_n][:2]:
        konec = len(q1) - 1 if q1 and q1[-1].startswith("Nechceme") else len(q1)
        q1.insert(min(konec, 4), f"Nově i: {b['segment'].split(' ', 1)[-1]}")
        n_z = b["zakazniku"]
        kdo = ("kupuje jeden váš zákazník" if n_z == 1 else f"kupují {n_z} vaši zákazníci" if n_z <= 4 else f"kupuje {n_z} vašich zákazníků")
        ev1.append({"text": f"Tip: {b['segment'].split(' ', 1)[-1]} – tohle od konkurence {kdo} "
                            f"({_tvar(b['pocet'], 'zakázka', 'zakázky', 'zakázek')} za {kc(b['objem'])} za 3 roky"
                            + (f", nejvíc {b['lidr']}" if b.get("lidr") else "") + ").",
                    "zdroj": "ISVZ", "rating": "A1"})

    # strategicky cil -> urcuje, co zpravodaj stavi nahoru (stavajici zakaznici / novi zadavatele / nove obory)
    k = ci.get("koncentrace")
    ev_s = []
    if k and k["zakazniku"] >= 2:
        ev_s.append({"text": f"Váš největší zákazník {k['top_nazev']} vám dává {k['top_podil'] * 100:.0f} % tržeb od státu, "
                             f"tři největší dohromady {k['top3_podil'] * 100:.0f} % (zákazníků máte {k['zakazniku']}).",
                     "zdroj": "ISVZ + Registr smluv", "rating": "A1"})
    t = ci.get("trend")
    if t and (t["posl12"] or t["pred12"]):
        ev_s.append({"text": f"Za poslední rok jste vyhráli {t['posl12']} soutěží, rok předtím {t['pred12']}.",
                     "zdroj": "ISVZ", "rating": "A1"})
    q_strat = ["Udržet a rozšířit stávající zákazníky", "Získat nové zákazníky ve svém oboru",
               "Proniknout do nového oboru", "Získávat větší zakázky"]
    if k and k["top_podil"] >= 0.4:
        q_strat[1] += " (být méně závislí na jednom úřadu)"
    if bez_historie:
        q_strat = ["Získat první zakázky od státu", "Začít jako subdodavatel větší firmy", "Zatím jen sledovat, co stát poptává"]

    # konkurenti ke sledovani: primi soupeři z ucasti, jinak lidri segmentu
    sb = ci.get("souboje") or []
    if sb:
        q_konk = [f"{x['nazev'][:60]} – společných soutěží: {x['stretu']}, vyhráli jste {x['my_vyhra']}, oni {x['oni_vyhra']}" for x in sb[:5]]
        ev_k = [{"text": "Tyhle firmy se nejčastěji hlásily do stejných soutěží jako vy. U každé vidíte, v kolika soutěžích jste se "
                         "potkali a kolikrát z nich vyhráli vy a kolikrát oni (zbytek vyhrál někdo jiný).",
                 "zdroj": "ISVZ (účastníci)", "rating": "A1"}]
    else:
        q_konk = [f"{x['nazev'][:60]} – největší dodavatel v oboru {x['segment'].split(' ', 1)[-1]}" for x in (ci.get("lidri") or [])[:5]]
        ev_k = [{"text": "U vašich soutěží data neuvádějí, kdo další se přihlásil – nabízím proto největší firmy ve vašem oboru.",
                 "zdroj": "ISVZ (vítězové)", "rating": "A1"}] if q_konk else []

    ev2 = ([{"text": f"8 z 10 vašich vyhraných zakázek mělo hodnotu {kc(_od(h))} – {kc(_do(h))}, nejčastěji kolem {kc(med)}. "
                     f"Největší byla za {kc(h['max_czk'])}.",
             "zdroj": "ISVZ", "rating": "A1"}] if med else [])
    ev3 = ([{"text": "Kde jste dosud zakázky dělali: " + ", ".join(f"{x['kraj']} ({x['pocet']}×)" for x in h["kraje"][:4] if x["kraj"]),
             "zdroj": "ISVZ (místo plnění)", "rating": "A1"}] if h["kraje"] else [])
    if s.get("adresa") or s.get("mesto"):
        ev3.append({"text": f"Vaše sídlo: {s.get('adresa') or s.get('mesto')}", "zdroj": "ARES", "rating": "A1"})
    ev4 = [{"text": "Certifikáty a oprávnění (ISO, autorizace, prověrky) se z veřejných rejstříků zjistit nedají, proto se ptám.",
            "zdroj": "–", "rating": "–"}]

    def ot(qid, cat, text, qr, multi, proc, ev):
        return {"id": qid, "category": cat, "question_text": text, "quick_replies": qr[:6], "allow_multiple": multi,
                "proc": proc, "evidence": ev}

    return {
        "status": "needs_clarification",
        "detected_summary": shr.strip(),
        "detected_vertical": vert,
        "questions": [
            ot("q1_scope", "Co děláte", "Čím se vaše firma hlavně živí?",
               q1, True, "Vyberte jen to, co opravdu děláte – podle toho hledám zakázky. Když tu vaše činnost není, napište ji "
                         "vlastními slovy (třeba „montáž klimatizací“).", ev1) if bez_historie else
            ot("q1_scope", "Co dodáváte", "Jaké zakázky chcete dostávat a jaké ne?",
               q1, True, "Označte obory, ze kterých chcete zakázky. „Nově i“ je obor, kde zatím nedodáváte, ale vaši zákazníci "
                         "ho kupují od konkurence. Co označíte „Nechceme“, to se vám ukazovat nebude.", ev1),
            ot("q5_strategy", "Cíl", "Čeho chcete ve veřejných zakázkách dosáhnout v příštím roce?",
               q_strat, False, ("Podle toho řadím zakázky ve zpravodaji. Jako subdodavatel můžete jít i do větších zakázek, "
                                "které byste sami nesplnili." if bez_historie else
                                "Podle toho dám nahoru buď zakázky od vašich stávajících zákazníků, nebo od nových, nebo z nového oboru."), ev_s),
            *([ot("q6_competitors", "Konkurence", "Které konkurenty chcete hlídat?",
                  q_konk, True, "Když vypíše zakázku úřad, u kterého tahle firma už dřív vyhrála, upozorním vás. "
                                "Víte pak, s kým v soutěži nejspíš budete a s jakou cenou počítat.", ev_k)] if q_konk else []),
            ot("q2_budget", "Velikost zakázek", "Jak velké zakázky chcete?",
               q2, True, "Zakázky, které jsou pro vás moc malé nebo moc velké, schovám.", ev2),
            ot("q2_prep", "Čas na nabídku", "Kolik dní nejméně potřebujete na přípravu nabídky?",
               q_prep, False, "Zakázky, kde zbývá na podání nabídky méně dní, vám neukážu – nestihli byste je.", []),
            ot("q3_region", q3_cat, q3_text, q3, False,
               ("Vzdálené zakázky se kvůli dopravě nevyplatí – ty mimo váš dojezd schovám." if lokalni else
                "Zakázky s místem dodání, kam zboží nedovezete, schovám." if vert == "dodavky_zbozi" else
                "U vašeho oboru nezáleží tolik na místě, spíš na tom, jestli dodáváte hotové řešení, nebo lidi."), ev3),
            ot("q4_qualification", "Certifikáty a oprávnění", "Co z toho máte? Zadavatelé to často vyžadují.",
               q4, True, "Zakázky, kde zadavatel chce něco, co nemáte (zákon o zakázkách § 77–79), označím jako nevhodné.", ev4),
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
    rozsirit = []  # sousedni obory, kde nakupuji stavajici zakaznici (nabidnuto z CI analyzy)
    div_podle_nazvu = {norm(v): k for k, v in CPV_DIV.items()}
    for x in sel1:
        if norm(x).startswith(("vyhnout se", "nechceme")):
            neg.append(x.split(":", 1)[-1].strip())
        elif norm(x).startswith(("rozsirit do", "nove i")):
            nazev = x.split(":", 1)[-1].strip()
            if div_podle_nazvu.get(norm(nazev)):
                rozsirit.append(div_podle_nazvu[norm(nazev)] + "000000")
            chci.append(nazev)
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
    # NACE v ARES je slaby signal: velke firmy maji zapsane desitky zivnosti (Alza i "stravovani" a "doprava").
    # Kdyz ma firma vlastni historii zakazek, NACE kody se pridaji jen ty, ktere si uzivatel sam vybral.
    ma_historii = sum(c["pocet"] for c in h["top_cpv"]) >= 5
    vybrane_nace = [codes for label, codes in nc if norm(label) in chci_seg] or ([] if ma_historii else [codes for _, codes in nc[:1]])
    for codes in vybrane_nace:
        main += [c for c in codes if c not in main]
    main = (main[:7] + [c for c in rozsirit if c not in main[:7]])[:9] or VERT_CPV_DEFAULT[vert][:2]
    secondary = [c["cpv"] for c in h["top_cpv"] if c["cpv"] not in main][:8]
    # firma bez historie: jen cinnosti, ktere si vybrala (ne vsech 10 zivnosti z ARES - jinak by dostala i uklid)
    secondary = secondary[:10] or ([] if vybrane_nace else VERT_CPV_DEFAULT[vert][2:])

    # Q2 rozpocet + priprava (dny: samostatna otazka q2_prep; starsi format je mel v q2_budget)
    sel2, txt2 = _odpoved_text(odp, "q2_budget")
    sel2p, txt2p = _odpoved_text(odp, "q2_prep")
    sel2 = sel2 + [x for x in sel2p + [txt2p] if x]
    lo = hi = None
    vzmr = False
    prep = 10
    for x in sel2 + [txt2]:
        if not x:
            continue
        nx = norm(x)
        if "priprav" in nx or "dni" in nx or "dnu" in nx or "den" in nx:
            m = re.search(r"(\d+)", x)
            if m:
                prep = int(m.group(1))
            continue
        if nx.startswith("jako dosud"):
            a, b = _od(h), _do(h)
        else:
            a, b = _castka(x)
        if "vzmr" in nx or nx.startswith("male zakazky"):
            vzmr = True
            a, b = 0, (6e6 if vert == "stavebnictvi" else 2e6)
        if a is not None:
            lo = a if lo is None else min(lo, a)
        if b is not None:
            hi = b if hi is None else max(hi, b)
        elif a is not None and not nx.startswith("jako dosud"):
            hi = None if hi is None or a >= (hi or 0) else hi
    if lo is None and hi is None and h["median_zakazky_czk"]:
        lo, hi = (h["p25_czk"] or 0) * 0.5, max((h["p75_czk"] or 0) * 2, h.get("p90_czk") or 0)
    if hi is None and not h["median_zakazky_czk"]:
        # firma bez historie a bez odpovedi: nedoporucovat megazakazky (metro za miliardy pro malou firmu)
        hi = {"stavebnictvi": 20e6, "it_sw": 10e6}.get(vert, 6e6)
        lo = lo or 0
        vzmr = True
    if lo is not None and lo < 2e6:
        vzmr = True
    zaokr = lambda x: None if x is None else float(round(x, -3) if x < 1e6 else round(x, -4))  # bez halerovych desetin
    lo, hi = zaokr(lo), zaokr(hi)

    # Q3 regiony / model spoluprace
    sel3, txt3 = _odpoved_text(odp, "q3_region")
    regiony, max_km, model = [], None, None
    volba = norm(" ".join(sel3) + " " + txt3)
    if lokalni or vert == "dodavky_zbozi":
        hq = s.get("nuts3")
        if any(x in volba for x in ("cela cr", "cele cr", "cela republika", "kamkoli", "cele cesko")) or (not volba.strip() and not lokalni):
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
        model = ("obojí" if "oboji" in volba else "bodyshopping" if "body" in volba or "pronaj" in volba
                 else "na klíč" if "klic" in volba else None)

    # Q4 kvalifikace
    sel4, txt4 = _odpoved_text(odp, "q4_qualification")
    kval = [x for x in sel4 if "konsorc" not in norm(x) and "subdod" not in norm(x)]
    kval += [k.strip() for k in re.split(r"[;,\n]", txt4) if k.strip()]
    konsorcium = (any("konsorc" in norm(x) or "subdod" in norm(x) for x in sel4) or "konsorc" in norm(txt4)
                  or "subdodav" in norm(" ".join(_odpoved_text(odp, "q5_strategy")[0])))

    # Q5 strategicky cil
    sel5, txt5 = _odpoved_text(odp, "q5_strategy")
    v5 = norm(" ".join(sel5) + " " + txt5)
    strategie = ("novi_zadavatele" if "prvni zakazky" in v5 or "subdodav" in v5 else None) or (
                 "stavajici" if "stavajic" in v5 or "branit" in v5
                 else "novi_zadavatele" if "nove zadavatele" in v5 or "nove zakazniky" in v5
                 else "nove_obory" if "sousedni" in v5 or "obor" in v5 else "vetsi_zakazky" if "vetsi" in v5 else None)
    if strategie == "vetsi_zakazky" and hi:
        hi = hi * 2  # cil rust: pripustit i vetsi zakazky nez dosud

    # Q6 sledovani konkurenti (jen firmy z dat - zadne odhady)
    sel6, txt6 = _odpoved_text(odp, "q6_competitors")
    ci = rc.get("ci") or {}
    znami = {norm(x["nazev"][:60]): x for x in (ci.get("souboje") or []) + (ci.get("lidri") or [])}
    watch = []
    for x in sel6:
        hit = znami.get(norm(x.split(" – ", 1)[0]))
        if hit and hit["ico"] not in [w["ico"] for w in watch]:
            watch.append({"ico": hit["ico"], "nazev": hit["nazev"]})
    for m in re.findall(r"\b\d{8}\b", txt6):  # IČO dopsana rucne
        if m not in [w["ico"] for w in watch]:
            watch.append({"ico": m, "nazev": None})

    dealbreakers = [f"lhůta na nabídku kratší než {prep} dní"]
    if hi:
        dealbreakers.append(f"zakázky nad {kc(hi * 1.5)} (mimo kapacitu)")
    if max_km:
        dealbreakers.append(f"místo plnění dál než {max_km} km od sídla")
    dealbreakers += [f"předmět: {n}" for n in neg[:3]]

    # klicova slova z historie a webu
    txt = " ".join(h["nazvy_vyher"] + h["registr_smluv"]["predmety"] + [((rc.get("web") or {}).get("popis") or "")] + chci)
    stopz = {norm(z["nazev"] or "") for z in h["top_zadavatele"]}
    kw = [w for w, _ in Counter(w for w in norm(txt).split()
                                if len(w) > 4 and w not in STOP_KW and not w.isdigit() and not any(w in z for z in stopz)).most_common(12)]
    if not ma_historii:  # firma bez zakazek: slova typicka pro vybrane cinnosti (klimatizace, vzduchotechnika...)
        vybrane = [label for label, _ in nc if norm(label) in chci_seg] or [label for label, _ in nc[:1]]
        kw = list(dict.fromkeys(nace_slova(rc, vybrane) + kw))[:15]

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
            "cpv_codes": {"main": main, "secondary": secondary}, "cpv_zdroj": h.get("cpv_zdroj") or "",
            "keywords": kw, "negative_keywords": neg,
            "regions_nuts3": regiony, "max_distance_km": max_km, "cooperation_model": model,
            "budget": {"min_czk": lo, "max_czk": hi, "vzmr_interest": vzmr}, "min_prep_days": prep,
            "qualifications": kval, "consortium_ok": konsorcium, "dealbreakers": dealbreakers,
            "whitelist_procurer_icos": [z["ico"] for z in h["top_zadavatele"][:8]], "blacklist_procurer_icos": [],
            "strategy": strategie, "watchlist": watch[:10],
        },
    }


# ------------------------------------------------------------------ validace vystupu LLM
CPV8 = re.compile(r"^\d{8}$")


# otazky, ktere smi model preformulovat; konkurenty (q6) a dukazy bereme vzdy z dat, aby model nevymyslel firmy
PREFORMULOVAT = {"q1_scope", "q5_strategy", "q2_budget", "q3_region", "q4_qualification"}


def _ocisti_faze1(d, zaloha):
    llm_q = {}
    for i, q in enumerate(d.get("questions") or []):
        if isinstance(q, dict) and isinstance(q.get("question_text"), str):
            qid = q.get("id") if q.get("id") in PREFORMULOVAT else None
            if qid is None and i < 4:  # starsi format bez id: poradi q1-q4
                qid = ["q1_scope", "q2_budget", "q3_region", "q4_qualification"][i]
            if qid and qid not in llm_q:
                llm_q[qid] = q
    out = []
    for z in zaloha["questions"]:
        q = llm_q.get(z["id"]) if z["id"] in PREFORMULOVAT else None
        if not q:
            out.append(z)
            continue
        qr = q.get("quick_replies") if isinstance(q.get("quick_replies"), list) else []
        out.append({**z, "question_text": q["question_text"][:600],
                    "quick_replies": [str(x)[:200] for x in qr][:6] or z["quick_replies"],
                    "allow_multiple": bool(q.get("allow_multiple", z["allow_multiple"])),
                    "category": str(q.get("category") or z["category"])[:60]})
    d["questions"] = out
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
    main = fix(cpv.get("main")) or z["cpv_codes"]["main"]
    if z.get("cpv_zdroj"):  # kody z historie firmy maji prednost, AI je jen doplni
        main = list(dict.fromkeys(z["cpv_codes"]["main"][:5] + main))[:8]
    p["cpv_codes"] = {"main": main, "secondary": [c for c in fix(cpv.get("secondary")) if c not in main]}
    p["cpv_zdroj"] = z.get("cpv_zdroj") or ""
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
    p["watchlist"] = z.get("watchlist") or []  # jen firmy vybrane z dat (model je nesmi pridavat)
    if p.get("strategy") not in ("stavajici", "novi_zadavatele", "nove_obory", "vetsi_zakazky", None):
        p["strategy"] = z.get("strategy")
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
    srazky = []
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
               "odpoved": f"obor zakázky ({', '.join(dict.fromkeys(CPV_DIV.get(c[:2], c) for c in cpvs[:2])) or 'neuveden'}) sedí s vaším na {cs} %, název zakázky se s vaším popisem "
                          + ("shoduje hodně" if sim >= 0.25 else "shoduje částečně" if sim >= 0.1 else "skoro neshoduje"), "skore": sk})

    # 2 lokalita: plynuly pokles s dojezdovou vzdalenosti (logisticka krivka kolem limitu)
    kn, misto = misto_zakazky(z)
    s = profil.get("sidlo") or {}
    lokalni = profil.get("vertical") in LOKALNI_VERTIKALY
    if misto and s.get("lat"):
        km = round(vzdalenost_km((s["lat"], s["lon"]), misto))
        limit = profil.get("max_distance_km") or (150 if lokalni else None)
        v_regionu = "CZ0" in profil["regions_nuts3"] or kn in profil["regions_nuts3"]
        if lokalni:
            L = limit or 150
            sk = 100 / (1 + math.exp((km - L) / (0.2 * L)))      # km = limit -> 50, polovina limitu -> 92
            sk = sk * (1 if v_regionu else 0.7)
            odp = f"{nazev_kraje(kn)}, cca {km} km od sídla ({s.get('mesto') or s.get('kraj')}) po silnici"
            if limit and km > limit * 1.3:
                srazky.append(_srazka(f"místo plnění {km} km od sídla (limit {limit} km)",
                                      min(0.8, 0.3 + (km / limit - 1.3) * 0.5), "lokalita"))
        else:
            sk = 100 if v_regionu else max(60, 100 - km / 8)
            odp = f"{nazev_kraje(kn)}, {km} km – u vašeho oboru lze plnit převážně vzdáleně"
        kr.append({"klic": "lokalita", "otazka": "Vyplatí se nám tam jezdit?", "odpoved": odp, "skore": round(sk), "km": km})
    else:
        kr.append({"klic": "lokalita", "otazka": "Vyplatí se nám tam jezdit?", "odpoved": "místo plnění neuvedeno", "skore": None})

    # 3 velikost: vzdalenost od vaseho rozsahu v logaritmickem meritku (2x mimo rozsah ~ 60 bodu, 4x ~ 15)
    hod = z.get("predpokladana_hodnota")
    b = profil.get("budget") or {}
    lo, hi = b.get("min_czk"), b.get("max_czk")
    if hod:
        d = 0.0
        if hi and hod > hi:
            d = math.log10(hod / hi)
        elif lo and hod < lo:
            d = math.log10(lo / hod) * 0.6   # mala zakazka vadi mene nez prilis velka
        sk = 100 * math.exp(-(d ** 2) / (2 * 0.25 ** 2))
        if hi and hod > hi * 3:
            srazky.append(_srazka(f"hodnota {kc(hod)} výrazně nad vaší kapacitou ({kc(hi)})",
                                  min(0.8, 0.3 + math.log10(hod / (hi * 3)) * 0.5), "velikost"))
        kr.append({"klic": "velikost", "otazka": "Sedí velikost zakázky na naši kapacitu?",
                   "odpoved": f"{kc(hod)} (váš rozsah {kc(lo) if lo else '0'} – {kc(hi) if hi else 'bez limitu'})", "skore": round(sk)})
    else:
        kr.append({"klic": "velikost", "otazka": "Sedí velikost zakázky na naši kapacitu?", "odpoved": "hodnota neuvedena", "skore": None})

    # 4 cas: zbyvajici dny vuci dobe, kterou potrebujete na pripravu nabidky
    lh = parse_date(z.get("lhuta_nabidek"))
    prep = profil.get("min_prep_days") or 10
    if lh:
        dni = (lh - today).days
        if dni < 0:
            kr.append({"klic": "cas", "otazka": "Stihneme připravit nabídku?", "odpoved": f"lhůta uplynula {lh.isoformat()} (ukázka z historie)", "skore": None, "uplynula": True})
        else:
            sk = 100 * (1 - math.exp(-2.3 * dni / prep))     # = potreba -> 90, polovina -> 68, ctvrtina -> 44
            if dni < prep * 0.5:
                srazky.append(_srazka(f"na nabídku zbývá jen {dni} dní (potřebujete {prep})",
                                      0.5 + 0.4 * (1 - dni / (prep * 0.5)), "cas"))
            kr.append({"klic": "cas", "otazka": "Stihneme připravit nabídku?", "odpoved": f"zbývá {dni} dní do {lh.isoformat()} (potřebujete {prep})", "skore": round(sk)})
    else:
        kr.append({"klic": "cas", "otazka": "Stihneme připravit nabídku?", "odpoved": "lhůta neuvedena", "skore": None})

    # 5 zadavatel: historie spoluprace (kolikrat jste u nej vyhrali / meli smlouvu)
    zi = z.get("zadavatel_ico")
    n_hist = (klienti.get(zi, 0) if isinstance(klienti, dict) else (1 if zi in klienti else 0)) if zi else 0
    if zi and zi in (profil.get("blacklist_procurer_icos") or []):
        srazky.append(_srazka("zadavatel je na vašem blacklistu", 0.9, "zadavatel"))
        sk, odp = 0, "na blacklistu"
    elif zi and zi in (profil.get("whitelist_procurer_icos") or []):
        sk, odp = 100, "oblíbený zadavatel (whitelist)"
    elif n_hist:
        sk = 55 + 45 * (1 - math.exp(-n_hist / 1.5))
        odp = f"známý zákazník – {n_hist}× výhra nebo smlouva"
    else:
        sk, odp = 55, "nový zadavatel"
    kr.append({"klic": "zadavatel", "otazka": "Známe zadavatele?", "odpoved": f"{z.get('zadavatel_nazev') or '?'} – {odp}", "skore": round(sk)})

    # 6 konkurence: ocekavany pocet nabidek a dominance nejvetsiho dodavatele v segmentu
    k = konk.get((z.get("cpv_hlavni") or "")[:2]) or {}
    if k.get("prumer_nabidek") or k.get("top_podil") is not None:
        pn = k.get("prumer_nabidek")
        sk = 100 * math.exp(-(pn - 1) / 4) if pn else 55        # 1 nabidka -> 100, 3 -> 61, 5 -> 37
        if k.get("top_podil") and k["top_podil"] > 0.4:
            sk *= 1 - (k["top_podil"] - 0.4)                     # jeden dodavatel vyhrava vetsinu -> horsi sance
        odp = (f"v oboru průměrně {pn:.1f} nabídky".replace(".", ",") if pn else "počet nabídek neznámý") + \
              (f", největší dodavatel vyhrává {k['top_podil'] * 100:.0f} %" if k.get("top_podil") is not None else "")
        kr.append({"klic": "konkurence", "otazka": "Jak silná je konkurence?", "odpoved": odp, "skore": round(max(5, sk))})
    else:
        kr.append({"klic": "konkurence", "otazka": "Jak silná je konkurence?", "odpoved": "málo dat o oboru", "skore": None})

    # 7 kvalifikace: obrat a reference z verejnych dat + co zadavatel uvadi + profil
    sk7, odp7, ko7 = _kvalifikace(z, profil, kap)
    if ko7:
        srazky.append(_srazka(ko7, 0.6, "kvalifikace"))
    kr.append({"klic": "kvalifikace", "otazka": "Splníme kvalifikaci (obrat, reference)?", "odpoved": odp7, "skore": sk7, "rucne": True})

    # dealbreakery: negativni slova
    nz = " " + norm(z.get("nazev")) + " "
    for n in profil.get("negative_keywords") or []:
        nn = norm(n)
        if nn and (f" {nn} " in nz or (len(nn) > 6 and nn in nz)):
            srazky.append(_srazka(f"obsahuje vyloučené slovo „{n}“", 0.7, "slova"))

    for c in kr:
        c["vaha"] = VAHY[c["klic"]] // (4 if c["klic"] == "lokalita" and not lokalni else 1)
    return skore_z_kriterii(kr, srazky)


def _srazka(duvod, zavaznost, klic):
    return {"duvod": duvod, "zavaznost": round(max(0.0, min(0.95, zavaznost)), 2), "klic": klic}


def skore_z_kriterii(kr, srazky):
    """Celkove skore = vazeny prumer kriterii (zaklad) x srazky za vylucujici duvody.
    Kazda srazka nasobi skore (1 - zavaznost), takze i nevhodne zakazky zustanou serazene podle toho,
    jak moc nesedi (driv mely vsechny 25). Vraci i rozpad: kolik bodu prinesla ktera otazka."""
    platne = [c for c in kr if c["skore"] is not None]
    suma_vah = sum(c["vaha"] for c in platne)
    for c in kr:
        c["body"] = round(c["skore"] * c["vaha"] / suma_vah, 1) if (c["skore"] is not None and suma_vah) else None
    zaklad = sum(c["skore"] * c["vaha"] for c in platne) / suma_vah if suma_vah else 0
    faktor = 1.0
    for s in srazky:
        faktor *= 1 - s["zavaznost"]
    celk = round(zaklad * faktor)
    ko = [s["duvod"] for s in srazky if s["zavaznost"] >= 0.5]
    verdikt = "nevhodné" if ko else "doporučeno" if celk >= 70 else "zvážit" if celk >= 50 else "spíš ne"
    return {"skore": celk, "zaklad": round(zaklad), "srazky": srazky, "verdikt": verdikt, "ko": ko, "kriteria": kr}


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
    klienti = _klienti(con, profil["ico"])
    watch = _sledovani(con, profil.get("watchlist") or [])
    strat = profil.get("strategy")
    max_ref = max((x for v in (kap or {}).get("reference", {}).values() for x in v), default=None)
    polozky = []
    for z in kand:
        v = vhodnost(z, profil, tf, qv, konk, today, klienti, kap)
        if v["kriteria"][0]["skore"] < 35:  # predmet vubec nesedi -> do zpravodaje nepatri
            continue
        lh = parse_date(z.get("lhuta_nabidek"))
        zi = z.get("zadavatel_ico")
        znamy = bool(zi and klienti.get(zi))
        cil = {"stavajici": znamy and "váš stávající zákazník", "novi_zadavatele": (zi and not znamy) and "nový zadavatel",
               "vetsi_zakazky": (max_ref and (z.get("predpokladana_hodnota") or 0) > max_ref) and "větší než vaše dosavadní maximum"
               }.get(strat) or None
        polozky.append({"sledovani": watch.get(zi, []) if zi else [], "cil": cil,"id": z["id"], "nazev": z["nazev"], "zadavatel": z["zadavatel_nazev"], "zadavatel_ico": z["zadavatel_ico"],
                        "kraj": z["kraj"], "hodnota": z["predpokladana_hodnota"], "datum": z["datum_zahajeni"],
                        "lhuta": (z.get("lhuta_nabidek") or "")[:10], "otevrena": bool(lh and lh >= today), **odkazy(z),
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


def _sledovani(con, watch):
    """Zadavatel -> [{"nazev", "vyher"}] sledovanych konkurentu, kteri u nej uz vyhrali (signal pro rozhodnuti, zda podat)."""
    icos = [w["ico"] for w in watch if w.get("ico")][:10]
    if not icos:
        return {}
    nazvy = {w["ico"]: w.get("nazev") for w in watch}
    from .api import _nazvy
    nazvy.update({k: v for k, v in _nazvy(con, icos).items() if v})
    out = defaultdict(list)
    for zi, d, n in con.execute(
            f"""SELECT z.zadavatel_ico, v.dodavatel_ico, COUNT(*) FROM vitezove v JOIN zakazky z ON z.id=v.zakazka_id
                WHERE v.dodavatel_ico IN ({','.join('?' * len(icos))}) AND z.zadavatel_ico IS NOT NULL
                GROUP BY z.zadavatel_ico, v.dodavatel_ico""", icos):  # nosec B608 - jen otazniky
        out[zi].append({"ico": d, "nazev": nazvy.get(d) or d, "vyher": n})
    for v in out.values():
        v.sort(key=lambda x: -x["vyher"])
    return out


def _klienti(con, ico):
    """Zadavatel -> kolikrat u nej firma vyhrala (RVZ) nebo s nim ma smlouvu (Registr smluv)."""
    k = Counter()
    for zi, n in con.execute("""SELECT z.zadavatel_ico, COUNT(*) FROM vitezove v JOIN zakazky z ON z.id=v.zakazka_id
                                WHERE v.dodavatel_ico=? AND z.zadavatel_ico IS NOT NULL GROUP BY z.zadavatel_ico""", (ico,)):
        k[zi] += n
    for zi, n in con.execute("SELECT zadavatel_ico, SUM(pocet) FROM smlouvy_odberatele WHERE ico=? GROUP BY zadavatel_ico", (ico,)):
        if zi:
            k[zi] += n or 0
    return k


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
    return vhodnost(z, profil, tf, qv, _konkurence(con), today or date.today(), _klienti(con, profil["ico"]),
                    kap=kapacita(con, profil["ico"], today)) | odkazy(z)
