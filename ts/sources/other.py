"""ARES (bez registrace), Hlidac statu (token zdarma), Google News RSS (bez registrace)."""
import xml.etree.ElementTree as ET
from datetime import datetime
from email.utils import parsedate_to_datetime

from ..util import http_get, log, nuts_to_kraj


# ---------------- ARES ----------------
def ares_firma(base, ico):
    """GET https://ares.gov.cz/ekonomicke-subjekty-v-be/rest/ekonomicke-subjekty/{ico}"""
    r = http_get(f"{base}{ico}", headers={"Accept": "application/json"}, timeout=30)
    if r.status_code == 404:
        return None
    if r.status_code != 200:
        raise RuntimeError(f"ARES {ico}: HTTP {r.status_code}")
    d = r.json()
    sidlo = d.get("sidlo") or {}
    nace = d.get("czNace2008") or d.get("czNace") or []
    return {
        "ico": d.get("ico") or ico,
        "nazev": d.get("obchodniJmeno"),
        "sidlo": sidlo.get("textovaAdresa"),
        "kraj": sidlo.get("nazevKraje"),
        "nace": ",".join(nace),
        "pravni_forma": d.get("pravniForma"),
        "datum_vzniku": d.get("datumVzniku"),
        "datum_zaniku": d.get("datumZaniku"),
    }


# ---------------- Hlidac statu ----------------
def hlidac_zakazky(base, token, dotaz, max_stran=5):
    """GET {base}verejnezakazky/hledat?dotaz=...&strana=N  (hlavicka Authorization: Token xxx)"""
    out = []
    for strana in range(1, max_stran + 1):
        r = http_get(f"{base}verejnezakazky/hledat", params={"dotaz": dotaz, "strana": strana},
                     headers={"Authorization": f"Token {token}"}, timeout=60)
        if r.status_code == 401:
            raise RuntimeError("Hlidac statu: neplatny token (HTTP 401)")
        if r.status_code != 200:
            log("Scout", f"Hlidac statu strana {strana}: HTTP {r.status_code}, koncim")
            break
        d = r.json()
        res = d.get("results") or d.get("Results") or []
        if not res:
            break
        out.extend(res)
        if len(out) >= (d.get("total") or d.get("Total") or 0):
            break
    return out


# ---------------- Google News RSS ----------------
def google_news(base, dotaz, limit=10):
    r = http_get(base, params={"q": dotaz, "hl": "cs", "gl": "CZ", "ceid": "CZ:cs"}, timeout=30)
    if r.status_code != 200:
        return []
    root = ET.fromstring(r.content)
    items = []
    for it in root.iter("item"):
        pub = it.findtext("pubDate")
        try:
            d = parsedate_to_datetime(pub).date().isoformat() if pub else None
        except Exception:
            d = None
        src = it.find("source")
        items.append({
            "titulek": it.findtext("title"),
            "url": it.findtext("link"),
            "datum": d,
            "zdroj": src.text if src is not None else None,
            "dotaz": dotaz,
        })
        if len(items) >= limit:
            break
    return items
