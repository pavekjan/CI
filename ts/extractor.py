"""Agent EXTRACTOR - z libovolne struktury zaznamu (RVZ JSON, Hlidac statu JSON) vytahne
jednotny datovy model zakazky: CPV, lhuty, odhadovana hodnota, kriteria, zadavatel, vitezove...

Struktura otevrenych dat RVZ se meni s kazdou verzi dokumentace (2.6 -> 2.10 ...), proto
Extractor nepouziva pevne cesty, ale hleda klice podle vyznamu (normalizovany nazev klice +
nazvy nadrazenych objektu). Prikaz `python tenderscope.py inspect` vypise skutecne klice,
aby slo pravidla pripadne doladit v KEY_RULES nize.
"""
import hashlib
import re
from functools import lru_cache

from .util import clean_ico, ico_valid, nkey, norm, nuts_to_kraj, parse_date, to_float

CPV_RE = re.compile(r"^\d{8}(-\d)?$")
CPV_FULL = re.compile(r"^\d{8}-\d$")  # CPV s kontrolni cislici - jinde se tento tvar nevyskytuje
SUPPLIER_KEY = ("dodavatel", "ucastn", "uchazec", "vitez", "vybran", "subjekt", "contractor", "bidder", "tenderer",
                "smluvnistran", "konsorc", "spolecnik")
EXTRACTOR_VERZE = 3  # zvyseni = znovu zpracovat uz stazene soubory
# v3: dynamicke nakupni systemy (DNS 7, DNS 8, ...) a casti maji v open datech stejne evidencni cislo -> do ID se
#     pridava otisk nazvu, jinak se prepisovaly a vitez jedne zakazky (napr. Alza v DNS 8) zmizel; ID uz nikdy
#     neni kod NUTS ("CZ052"); vitezove z vice zaznamu teze zakazky se scitaji (casti zakazky)

# kontext (nazvy nadrazenych klicu), ve kterem hledame dodavatele / ucastniky
WINNER_CTX = ("dodavatel", "vitez", "vybran", "smluvnistrana", "uzavrenasmlouva", "smlouv", "contractor", "winner")
BIDDER_CTX = ("ucastn", "nabidk", "uchazec", "bidder", "tenderer")
AUTHORITY_CTX = ("zadavatel", "contractingauthority", "zadavajici", "objednatel")


def walk(obj, path=()):
    """Generuje (cesta_klicu, hodnota) pro vsechny listy struktury."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield from walk(v, path + (str(k),))
    elif isinstance(obj, list):
        for v in obj:
            yield from walk(v, path)
    else:
        yield path, obj


def walk_dicts(obj, path=()):
    """Generuje (cesta, dict) pro vsechny vnorene objekty."""
    if isinstance(obj, dict):
        yield path, obj
        for k, v in obj.items():
            yield from walk_dicts(v, path + (str(k),))
    elif isinstance(obj, list):
        for v in obj:
            yield from walk_dicts(v, path)


# podstromy, ve kterych nikdy nejsou udaje o zakazce/vitezi a jsou obrovske (desitky dokumentu,
# historie zmen...) - jejich prochazeni zpomalovalo zpracovani az 10x
PRUNE = ("dokument", "priloh", "soubor", "historie", "vysvetlen", "komunik", "kontaktniosob")


@lru_cache(maxsize=20000)
def _nk(k):
    return nkey(k)


def _flatten(rec):
    """Jeden pruchod zaznamem (v poradi dokumentu): listy (hloubka, klic, kontext, hodnota)
    a objekty (kontext, dict, index rodicovskeho objektu). Klice se normalizuji jen jednou."""
    leaves, dicts = [], []

    def rec_walk(obj, ctxp, parent):
        if isinstance(obj, dict):
            ctx = "/".join(ctxp)
            me = len(dicts)
            dicts.append((ctx, obj, parent))
            for k, v in obj.items():
                kk = _nk(str(k))
                if any(w in kk for w in PRUNE):
                    continue
                if isinstance(v, (dict, list)):
                    rec_walk(v, ctxp + (kk,), me)
                else:
                    leaves.append((len(ctxp) + 1, kk, ctx, v))
        elif isinstance(obj, list):
            for v in obj:
                if isinstance(v, (dict, list)):
                    rec_walk(v, ctxp, parent)
                elif ctxp:
                    leaves.append((len(ctxp), ctxp[-1], "/".join(ctxp[:-1]), v))

    rec_walk(rec, (), None)
    return leaves, dicts


def _pick(leaves, key_test, ctx_test=None, value_test=None, prefer_short=True):
    best = None
    for depth, k, ctx, val in leaves:
        if val is None or val == "":
            continue
        if not key_test(k):
            continue
        if ctx_test and not ctx_test(ctx):
            continue
        if value_test and not value_test(val):
            continue
        if best is None or depth < best[0]:
            best = (depth, val)
    return best[1] if best else None


def _not_in(*words):
    return lambda ctx: not any(w in ctx for w in words)


def _in(*words):
    return lambda ctx: any(w in ctx for w in words)


def _num(v):
    return to_float(v) is not None


def _dict_ico(d):
    for k, v in d.items():
        kk = _nk(k)
        if kk in ("ico", "icododavatele", "icozadavatele", "identifikacnicislo", "ic") or kk.endswith("ico"):
            ico = clean_ico(v)
            if ico:
                return ico
    return None


def _dict_name(d):
    for k, v in d.items():
        kk = _nk(k)
        if isinstance(v, str) and (kk in ("nazev", "obchodnijmeno", "jmeno", "name", "nazevdodavatele", "nazevzadavatele",
                                          "uredninazev", "nazevfirmy") or kk.startswith("nazev")):
            return v.strip()
    return None


def _dict_price(d):
    best = None
    for k, v in d.items():
        kk = _nk(k)
        if ("cena" in kk or "hodnota" in kk or "price" in kk) and "predpokl" not in kk and "odhad" not in kk:
            f = to_float(v) if not isinstance(v, dict) else None
            if f is None and isinstance(v, dict):
                f = to_float(v.get("hodnota") or v.get("castka") or v.get("value"))
            if f is not None and f >= 1000:  # 1 Kc apod. = zastupna hodnota
                score = 3 if "bezdph" in kk else 1 if ("sdph" in kk or "vcetnedph" in kk) else 2
                if best is None or score > best[0]:
                    best = (score, f)
    return best[1] if best else None


def _truthy(v):
    return v is True or str(v).strip().lower() in ("true", "1", "ano", "yes")


RE_NE_ID = re.compile(r"[A-Z]{2}\d{1,3}|\d{8}(-\d)?")  # kod NUTS nebo CPV neni identifikator zakazky
RE_NIPEZ = re.compile(r"\bRVZ\d{8,12}\b")
RE_NEN = re.compile(r"\bN\d{3}/\d{2}/V\d{8}\b")
RE_VVZ = re.compile(r"\bZ\d{4}-\d{6}\b")


def id_zakazky(zdroj, zid, nazev):
    """Jedno evidencni cislo muze patrit vic zakazkam (zakazky v dynamickem nakupnim systemu, opakovane vyzvy),
    proto se k nemu pridava kratky otisk nazvu. Zaznamy teze zakazky (zahajeni, vysledek) maji stejny nazev."""
    if zid is None:
        return None
    nz = norm(nazev or "")
    if not nz:
        return f"{zdroj}:{zid}"
    return f"{zdroj}:{zid}:{hashlib.sha1(nz.encode('utf-8'), usedforsecurity=False).hexdigest()[:6]}"


def identifikatory(leaves, zid=None):
    """Cisla, podle kterych jde zakazku najit na internetu: Identifikator NIPEZ (RVZ...), systemove cislo NEN
    (N006/26/V...), evidencni cislo ve Vestniku (Z2026-...) a adresa profilu zadavatele. Hleda se podle tvaru
    hodnoty, ne podle nazvu pole, protoze se nazvy poli v open datech meni."""
    out = {"nipez_id": None, "nen_cislo": None, "vvz_cislo": None, "profil_url": None}
    if zid is not None and RE_VVZ.fullmatch(str(zid)):
        out["vvz_cislo"] = str(zid)
    for _, k, ctx, val in leaves:
        if not isinstance(val, str) or len(val) > 300:
            continue
        kc_ = k + "/" + ctx
        if any(w in kc_ for w in ("dodavatel", "ucastnik", "dokument", "priloh", "navazuj", "puvodn", "predchoz")):
            continue
        for pole, rx in (("nipez_id", RE_NIPEZ), ("nen_cislo", RE_NEN), ("vvz_cislo", RE_VVZ)):
            if not out[pole]:
                m = rx.search(val)
                if m:
                    out[pole] = m.group(0)
        if not out["profil_url"] and "profil" in kc_ and val.startswith(("https://", "http://")) and " " not in val:
            out["profil_url"] = val[:300]
    return out


def extract(rec, zdroj="rvz"):
    """Vrati (zakazka_dict, vitezove_list, ucastnici_list)."""
    leaves, dicts = _flatten(rec)

    zid = _pick(leaves, lambda k: k in ("id", "idvz", "kodvz", "systemoveciselnevz", "idzakazky", "evidencnicislo",
                                         "kodrvz", "identifikatorvz", "rvzid", "idrvz"),
                ctx_test=_not_in(*AUTHORITY_CTX, "dokument", "dodavatel", "ucastnik", "priloh", "formular"))
    if zid is None:
        zid = _pick(leaves, lambda k: k.endswith("id") or k.startswith("kod") or "evidencn" in k,
                    ctx_test=_not_in(*AUTHORITY_CTX, "dokument", "dodavatel", "ucastnik"),
                    value_test=lambda v: isinstance(v, (str, int)) and len(str(v)) >= 5
                    and not RE_NE_ID.fullmatch(str(v).strip()))

    nazev = _pick(leaves, lambda k: k in ("nazev", "nazevvz", "nazevzakazky", "nazevverejnezakazky", "title", "nazevzp"),
                  ctx_test=_not_in(*AUTHORITY_CTX, *WINNER_CTX, *BIDDER_CTX, "dokument", "priloh", "kriteri",
                                   "druh", "stav", "postup", "rezim", "nuts", "cpv", "mena", "zdroj"),
                  value_test=lambda v: isinstance(v, str) and len(v) > 3)

    # zadavatel
    zad_ico = zad_nazev = None
    for ctx, d, _p in dicts:
        if any(w in ctx for w in AUTHORITY_CTX) or any(_nk(k).startswith("icozadavatel") for k in d):
            zad_ico = zad_ico or _dict_ico(d)
            zad_nazev = zad_nazev or _dict_name(d)
            if zad_ico and zad_nazev:
                break
    if not zad_ico:
        zad_ico = clean_ico(_pick(leaves, lambda k: "ico" in k and "zadavatel" in k))

    # CPV
    cpvs = []
    for _, k, ctx, val in leaves:
        if isinstance(val, (str, int)):
            s = str(val).strip()
            if (("cpv" in ctx or "cpv" in k) and CPV_RE.match(s)) or CPV_FULL.match(s):
                s = s[:8]
                if s not in cpvs:
                    cpvs.append(s)
    cpv_hl = _pick(leaves, lambda k: "cpv" in k and ("hlav" in k or "main" in k),
                   value_test=lambda v: bool(CPV_RE.match(str(v).strip())))
    cpv_hl = str(cpv_hl)[:8] if cpv_hl else (cpvs[0] if cpvs else None)

    hodnota = _pick(leaves, lambda k: ("predpokl" in k or "odhad" in k or "estimated" in k) and ("hodnot" in k or "cena" in k or "value" in k) and "mena" not in k
                    and "sdph" not in k.replace("bezdph", ""),
                    value_test=_num)
    if hodnota is None:
        hodnota = _pick(leaves, lambda k: k in ("hodnota", "castka", "bezdph"),
                        ctx_test=_in("predpokl", "odhad"), value_test=_num)

    datum = _pick(leaves, lambda k: "datum" in k and any(w in k for w in ("zahaj", "uverejn", "zverejn", "publik", "vyhlas")) or k == "publicationdate",
                  value_test=lambda v: parse_date(v) is not None)
    if datum is None:
        datum = _pick(leaves, lambda k: k in ("datum", "datumvytvoreni", "created", "datumzahajenizp"),
                      value_test=lambda v: parse_date(v) is not None)

    lhuta = _pick(leaves, lambda k: ("lhut" in k or "deadline" in k) and ("nabid" in k or "podan" in k or "zadost" in k),
                  value_test=lambda v: parse_date(v) is not None)
    if lhuta is None:
        lhuta = _pick(leaves, lambda k: "lhut" in k or "deadline" in k, value_test=lambda v: parse_date(v) is not None)

    stav = _pick(leaves, lambda k: k in ("stav", "stavvz", "stavzakazky", "status", "nazevstavu", "stavzp"),
                 value_test=lambda v: isinstance(v, str))
    if stav is None:
        stav = _pick(leaves, lambda k: k in ("nazev", "text", "hodnota"), ctx_test=_in("stav"),
                     value_test=lambda v: isinstance(v, str))
    druh = _pick(leaves, lambda k: k.startswith("druh") or k in ("kind",), value_test=lambda v: isinstance(v, str))
    postup = _pick(leaves, lambda k: "postup" in k or "druhrizeni" in k or "typrizeni" in k,
                   value_test=lambda v: isinstance(v, str) and not v.isdigit())
    rezim = _pick(leaves, lambda k: "rezim" in k or k == "regime", value_test=lambda v: isinstance(v, str))
    nuts = _pick(leaves, lambda k: "nuts" in k, value_test=lambda v: isinstance(v, str) and v.upper().startswith("CZ"))
    pocet = _pick(leaves, lambda k: "pocet" in k and ("nabid" in k or "ucastn" in k), value_test=_num)
    url = _pick(leaves, lambda k: k in ("url", "odkaz", "odkaznazakazku", "urlzakazky", "profilurl", "detailurl"),
                ctx_test=_not_in("dokument", "priloh", *AUTHORITY_CTX),
                value_test=lambda v: isinstance(v, str) and v.startswith("http"))

    # hodnotici kriteria
    kriteria = []
    for ctx, d, _p in dicts:
        if "kriteri" in ctx:
            n = _dict_name(d) or d.get("popis") or d.get("text")
            if isinstance(n, str) and n.strip() and n.strip() not in kriteria:
                vaha = None
                for k, v in d.items():
                    if "vah" in _nk(k) or "weight" in _nk(k):
                        vaha = to_float(v)
                kriteria.append(f"{n.strip()}" + (f" ({vaha:g} %)" if vaha else ""))
    for _, k, _c, val in leaves:
        if "kriteri" in k and isinstance(val, str) and val.strip() and val not in kriteria and len(val) < 200:
            kriteria.append(val.strip())

    # vitezove a ucastnici
    # Pravidla (z realnych dat RVZ): dodavatel je jen objekt pod klicem typu dodavatel/ucastnik/vitez...
    # s IČO nebo nazvem firmy. Objekty smluv a casti maji take "nazev" a "cenu" - ty NEJSOU dodavatele
    # (jinak by se mezi "rivaly" objevily nazvy zakazek). Cena viteze muze byt o uroven vys (smlouva/cast).
    vitezove, ucastnici = {}, {}
    nazev_n = norm(nazev)
    pouzite_ceny = set()
    for i, (ctx, d, par) in enumerate(dicts):
        if any(w in ctx for w in AUTHORITY_CTX):
            continue
        last = ctx.rsplit("/", 1)[-1]
        supplierish = any(w in last for w in SUPPLIER_KEY)
        ico = _dict_ico(d)
        name = _dict_name(d)
        if not supplierish and not (ico and any(w in ctx for w in WINNER_CTX + BIDDER_CTX)):
            continue
        if not ico and not name:
            continue
        if name and nazev_n and norm(name) == nazev_n:
            name = None
            if not ico:
                continue
        if ico and ico == zad_ico:
            continue
        is_winner_flag = any(("vybran" in _nk(k) or "vitez" in _nk(k) or "uspesn" in _nk(k)) and _truthy(v)
                             for k, v in d.items())
        key = (ico or "", (name or "").strip())
        price = _dict_price(d)
        bidder = any(w in ctx for w in BIDDER_CTX) and not any(w in ctx for w in ("vitez", "vybran", "smlouv"))
        if bidder:
            ucastnici[key] = price
            if not is_winner_flag:
                continue
        elif not (any(w in ctx for w in WINNER_CTX) or is_winner_flag or "dodavatel" in last):
            continue
        if price is None:  # cena smlouvy/casti o uroven(e) vys - jen pro prvniho dodavatele te smlouvy
            p, hop = par, 0
            while p is not None and hop < 3 and price is None:
                if p not in pouzite_ceny:
                    price = _dict_price(dicts[p][1])
                    if price is not None:
                        pouzite_ceny.add(p)
                p, hop = dicts[p][2], hop + 1
        vitezove[key] = price if price is not None else vitezove.get(key)
    if not any(v for v in vitezove.values()):
        cena = _pick(leaves, lambda k: ("cena" in k or "hodnota" in k) and any(w in k for w in ("smluv", "konecn", "vysled"))
                     and "predpokl" not in k, value_test=_num)
        if cena is not None and len(vitezove) == 1 and (to_float(cena) or 0) >= 1000:
            k0 = next(iter(vitezove))
            vitezove[k0] = to_float(cena)

    zak = {
        "id": id_zakazky(zdroj, zid, nazev),
        "zdroj": zdroj,
        "nazev": nazev,
        "zadavatel_ico": zad_ico,
        "zadavatel_nazev": zad_nazev,
        "cpv": ",".join(cpvs),
        "cpv_hlavni": cpv_hl,
        "druh": druh,
        "postup": postup,
        "rezim": rezim,
        "stav": stav,
        "nuts": nuts,
        "kraj": nuts_to_kraj(nuts),
        "predpokladana_hodnota": (to_float(hodnota) if (to_float(hodnota) or 0) >= 1000 else None),  # "1 Kč" = nevyplneno
        "datum_zahajeni": (parse_date(datum).isoformat() if parse_date(datum) else None),
        "lhuta_nabidek": (str(lhuta)[:19] if lhuta else None),
        "pocet_nabidek": (int(to_float(pocet)) if pocet is not None and to_float(pocet) > 0 else None),  # 0 = neuvedeno
        "kriteria": " | ".join(kriteria[:8]),
        "url": url,
    }
    # kvalifikace (podminky ucasti), pokud je zdroj uvadi: text a pripadny pozadovany minimalni obrat
    kval, min_obrat = [], None
    for _, k, ctx, val in leaves:
        kc_ = k + "/" + ctx
        if isinstance(val, str) and ("kvalifik" in kc_ or "podminkyucast" in kc_ or "qualification" in kc_ or "selectioncriteri" in kc_):
            t = " ".join(val.split())
            if 3 < len(t) <= 400 and t not in kval and not t.replace(".", "").isdigit():
                kval.append(t)
        if ("obrat" in kc_ or "turnover" in kc_) and _num(val) and (to_float(val) or 0) >= 10_000:
            min_obrat = max(min_obrat or 0, to_float(val))
    zak["kvalifikace"] = " | ".join(kval[:6])[:1200] or None
    zak.update(identifikatory(leaves, zid))
    zak["min_obrat"] = min_obrat
    vit = [{"dodavatel_ico": k[0] or None, "dodavatel_nazev": k[1] or None, "cena_bez_dph": v} for k, v in vitezove.items()]
    uc = [{"dodavatel_ico": k[0] or None, "dodavatel_nazev": k[1] or None, "nabidkova_cena": v} for k, v in ucastnici.items()]
    return zak, vit, uc


def relevance(zak, obor_cfg):
    """Vrati duvod relevance pro obor (CPV prefix / klicove slovo) nebo None."""
    for c in (zak.get("cpv") or "").split(","):
        for p in obor_cfg["cpv_prefixy"]:
            if c and c.startswith(p):
                return f"CPV {c}"
    text = " " + norm(zak.get("nazev")) + " "
    for kw in obor_cfg["klicova_slova"]:
        if " " + norm(kw) + " " in text or (len(kw) > 6 and norm(kw) in text):
            return f"slovo '{kw}'"
    return None


def describe_keys(rec, max_lines=200):
    """Pro prikaz inspect: seznam cest klicu s ukazkou hodnoty."""
    seen = {}
    for path, val in walk(rec):
        p = ".".join(path)
        if p not in seen:
            seen[p] = val
    lines = []
    for p, v in list(seen.items())[:max_lines]:
        sv = repr(v)
        lines.append(f"{p:<70} {sv[:60]}")
    return lines
