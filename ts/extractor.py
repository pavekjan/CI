"""Agent EXTRACTOR - z libovolne struktury zaznamu (RVZ JSON, Hlidac statu JSON) vytahne
jednotny datovy model zakazky: CPV, lhuty, odhadovana hodnota, kriteria, zadavatel, vitezove...

Struktura otevrenych dat RVZ se meni s kazdou verzi dokumentace (2.6 -> 2.10 ...), proto
Extractor nepouziva pevne cesty, ale hleda klice podle vyznamu (normalizovany nazev klice +
nazvy nadrazenych objektu). Prikaz `python tenderscope.py inspect` vypise skutecne klice,
aby slo pravidla pripadne doladit v KEY_RULES nize.
"""
import re

from .util import clean_ico, ico_valid, nkey, norm, nuts_to_kraj, parse_date, to_float

CPV_RE = re.compile(r"^\d{8}(-\d)?$")

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


def _ctx(path):
    return "/".join(nkey(p) for p in path)


def _pick(leaves, key_test, ctx_test=None, value_test=None, prefer_short=True):
    cands = []
    for path, val in leaves:
        if not path or val in (None, ""):
            continue
        k = nkey(path[-1])
        ctx = _ctx(path[:-1])
        if not key_test(k):
            continue
        if ctx_test and not ctx_test(ctx):
            continue
        if value_test and not value_test(val):
            continue
        cands.append((len(path), path, val))
    if not cands:
        return None
    cands.sort(key=lambda c: c[0] if prefer_short else -c[0])
    return cands[0][2]


def _not_in(*words):
    return lambda ctx: not any(w in ctx for w in words)


def _in(*words):
    return lambda ctx: any(w in ctx for w in words)


def _num(v):
    return to_float(v) is not None


def _dict_ico(d):
    for k, v in d.items():
        kk = nkey(k)
        if kk in ("ico", "icododavatele", "icozadavatele", "identifikacnicislo", "ic") or kk.endswith("ico"):
            ico = clean_ico(v)
            if ico:
                return ico
    return None


def _dict_name(d):
    for k, v in d.items():
        kk = nkey(k)
        if isinstance(v, str) and (kk in ("nazev", "obchodnijmeno", "jmeno", "name", "nazevdodavatele", "nazevzadavatele",
                                          "uredninazev", "nazevfirmy") or kk.startswith("nazev")):
            return v.strip()
    return None


def _dict_price(d):
    best = None
    for k, v in d.items():
        kk = nkey(k)
        if ("cena" in kk or "hodnota" in kk or "price" in kk) and "predpokl" not in kk and "odhad" not in kk:
            f = to_float(v) if not isinstance(v, dict) else None
            if f is None and isinstance(v, dict):
                f = to_float(v.get("hodnota") or v.get("castka") or v.get("value"))
            if f is not None and f > 0:
                score = 2 if "bezdph" in kk else 1
                if best is None or score > best[0]:
                    best = (score, f)
    return best[1] if best else None


def _truthy(v):
    return v is True or str(v).strip().lower() in ("true", "1", "ano", "yes")


def extract(rec, zdroj="rvz"):
    """Vrati (zakazka_dict, vitezove_list, ucastnici_list)."""
    leaves = list(walk(rec))

    zid = _pick(leaves, lambda k: k in ("id", "idvz", "kodvz", "systemoveciselnevz", "idzakazky", "evidencnicislo",
                                         "kodrvz", "identifikatorvz", "rvzid", "idrvz"),
                ctx_test=_not_in(*AUTHORITY_CTX, "dokument", "dodavatel", "ucastnik", "priloh", "formular"))
    if zid is None:
        zid = _pick(leaves, lambda k: k.endswith("id") or k.startswith("kod") or "evidencn" in k,
                    ctx_test=_not_in(*AUTHORITY_CTX, "dokument", "dodavatel", "ucastnik"),
                    value_test=lambda v: isinstance(v, (str, int)) and len(str(v)) >= 5)

    nazev = _pick(leaves, lambda k: k in ("nazev", "nazevvz", "nazevzakazky", "nazevverejnezakazky", "title", "nazevzp"),
                  ctx_test=_not_in(*AUTHORITY_CTX, *WINNER_CTX, *BIDDER_CTX, "dokument", "priloh", "kriteri",
                                   "druh", "stav", "postup", "rezim", "nuts", "cpv", "mena", "zdroj"),
                  value_test=lambda v: isinstance(v, str) and len(v) > 3)

    # zadavatel
    zad_ico = zad_nazev = None
    for path, d in walk_dicts(rec):
        ctx = _ctx(path)
        if any(w in ctx for w in AUTHORITY_CTX) or any(nkey(k).startswith("icozadavatel") for k in d):
            zad_ico = zad_ico or _dict_ico(d)
            zad_nazev = zad_nazev or _dict_name(d)
            if zad_ico and zad_nazev:
                break
    if not zad_ico:
        zad_ico = clean_ico(_pick(leaves, lambda k: "ico" in k and "zadavatel" in k))

    # CPV
    cpvs = []
    for path, val in leaves:
        ctx = _ctx(path)
        if "cpv" in ctx and isinstance(val, (str, int)):
            s = str(val).strip()
            if CPV_RE.match(s):
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
    for path, d in walk_dicts(rec):
        if "kriteri" in _ctx(path):
            n = _dict_name(d) or d.get("popis") or d.get("text")
            if isinstance(n, str) and n.strip() and n.strip() not in kriteria:
                vaha = None
                for k, v in d.items():
                    if "vah" in nkey(k) or "weight" in nkey(k):
                        vaha = to_float(v)
                kriteria.append(f"{n.strip()}" + (f" ({vaha:g} %)" if vaha else ""))
    for path, val in leaves:
        if "kriteri" in nkey(path[-1]) and isinstance(val, str) and val.strip() and val not in kriteria and len(val) < 200:
            kriteria.append(val.strip())

    # vitezove a ucastnici
    vitezove, ucastnici = {}, {}
    for path, d in walk_dicts(rec):
        ctx = _ctx(path)
        if any(w in ctx for w in AUTHORITY_CTX):
            continue
        ico = _dict_ico(d)
        name = _dict_name(d)
        if not ico and not name:
            continue
        is_winner_flag = any(("vybran" in nkey(k) or "vitez" in nkey(k) or "uspesn" in nkey(k)) and _truthy(v)
                             for k, v in d.items())
        key = (ico or "", (name or "").strip())
        price = _dict_price(d)
        if any(w in ctx for w in BIDDER_CTX) and not any(w in ctx for w in ("dodavatel", "vitez", "vybran")):
            ucastnici[key] = price
            if is_winner_flag:
                vitezove[key] = price
        elif any(w in ctx for w in WINNER_CTX) or is_winner_flag:
            if ico == zad_ico:
                continue
            # cena muze byt i v nadrazenem objektu (smlouva -> dodavatel)
            vitezove[key] = price if price is not None else vitezove.get(key)
    if not any(v for v in vitezove.values()):
        cena = _pick(leaves, lambda k: ("cena" in k or "hodnota" in k) and any(w in k for w in ("smluv", "konecn", "vysled"))
                     and "predpokl" not in k, value_test=_num)
        if cena is not None and len(vitezove) == 1:
            k0 = next(iter(vitezove))
            vitezove[k0] = to_float(cena)

    zak = {
        "id": f"{zdroj}:{zid}" if zid is not None else None,
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
        "predpokladana_hodnota": to_float(hodnota),
        "datum_zahajeni": (parse_date(datum).isoformat() if parse_date(datum) else None),
        "lhuta_nabidek": (str(lhuta)[:19] if lhuta else None),
        "pocet_nabidek": int(to_float(pocet)) if pocet is not None else None,
        "kriteria": " | ".join(kriteria[:8]),
        "url": url,
    }
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
