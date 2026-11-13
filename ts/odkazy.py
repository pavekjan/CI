"""Odkazy na zakazku a identifikatory, podle kterych ji firma najde na internetu.

- NEN (Narodni elektronicky nastroj): https://nen.nipez.cz/verejne-zakazky/detail-zakazky/N006-26-V00015651
  (systemove cislo N006/26/V00015651, lomitka se v adrese meni na pomlcky) - zadavaci dokumentace ke stazeni
- Vestnik verejnych zakazek: https://vvz.nipez.cz/formulare-zakazky/Z2026-033254 (evidencni cislo zakazky)
- Hlidac statu: hledani podle Identifikatoru NIPEZ (RVZ2600096641), evidencniho cisla nebo nazvu a ICO zadavatele
- profil zadavatele: adresa z open dat, pokud ji zdroj uvadi
"""
import re
from urllib.parse import quote

from .extractor import RE_NEN, RE_NIPEZ, RE_VVZ

HLIDAC_VZ = "https://www.hlidacstatu.cz/verejnezakazky/hledat?Q="


def _g(z, k):
    try:
        return z[k]
    except (KeyError, IndexError):
        return None


def identifikatory(z):
    zid = str(_g(z, "id") or "").split(":")[1] if ":" in str(_g(z, "id") or "") else ""
    nipez = _g(z, "nipez_id") or (zid if RE_NIPEZ.fullmatch(zid) else None)
    nen = _g(z, "nen_cislo") or (zid if RE_NEN.fullmatch(zid) else None)
    vvz = _g(z, "vvz_cislo") or (zid if RE_VVZ.fullmatch(zid) else None)
    return {"nipez_id": nipez, "nen_cislo": nen, "vvz_cislo": vvz}


def _https(u):
    return u if isinstance(u, str) and re.match(r"^https?://[^\s\"'<>]+$", u) else None


def odkazy(z):
    """Vraci {"url": nejlepsi odkaz, "odkazy": [{nazev, url}], nipez_id, nen_cislo, vvz_cislo}."""
    ids = identifikatory(z)
    out = []
    if ids["nen_cislo"]:
        out.append({"nazev": "NEN – detail a zadávací dokumentace",
                    "url": "https://nen.nipez.cz/verejne-zakazky/detail-zakazky/" + ids["nen_cislo"].replace("/", "-")})
    src = _https(_g(z, "url"))
    if src:
        out.append({"nazev": "Detail zakázky (zdroj)", "url": src})
    prof = _https(_g(z, "profil_url"))
    if prof and prof != src:
        out.append({"nazev": "Profil zadavatele", "url": prof})
    if ids["vvz_cislo"]:
        out.append({"nazev": "Věstník veřejných zakázek", "url": "https://vvz.nipez.cz/formulare-zakazky/" + ids["vvz_cislo"]})
    if ids["nipez_id"] or ids["vvz_cislo"]:
        q = ids["nipez_id"] or ids["vvz_cislo"]
    else:
        nazev = " ".join(str(_g(z, "nazev") or "").replace('"', " ").split())[:90]
        q = f'"{nazev}"' + (f" icozadavatel:{_g(z, 'zadavatel_ico')}" if _g(z, "zadavatel_ico") else "")
    out.append({"nazev": "Hlídač státu – vyhledat zakázku", "url": HLIDAC_VZ + quote(q)})
    if _g(z, "zadavatel_ico"):
        out.append({"nazev": "Zadavatel na Hlídači státu", "url": f"https://www.hlidacstatu.cz/subjekt/{_g(z, 'zadavatel_ico')}"})
    return {"url": out[0]["url"], "odkazy": out, **ids}
