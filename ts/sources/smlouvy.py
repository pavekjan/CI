"""Registr smluv - otevrena data (bez registrace).

https://data.smlouvy.gov.cz/index.xml  -> seznam mesicnich dumpu
https://data.smlouvy.gov.cz/dump_YYYY_MM.xml -> vsechny smlouvy zverejnene v mesici
Dumpy jsou velke (stovky MB), proto se ctou streamovane (iterparse) a ukladaji se
jen smlouvy relevantni pro obor nebo pro zname dodavatele/zadavatele.
"""
import os
import re
import xml.etree.ElementTree as ET

from ..util import CACHE_DIR, download, http_get, log, norm, clean_ico, to_float


def _local(tag):
    return tag.rsplit("}", 1)[-1]


def _child(el, name):
    for c in el:
        if _local(c.tag) == name:
            return c
    return None


def _text(el, name):
    c = _child(el, name)
    return c.text.strip() if c is not None and c.text else None


def fetch_index(base):
    r = http_get(base + "index.xml", timeout=60)
    r.raise_for_status()
    # bezpecnost: viz SECURITY.md (XML z overenych statnich zdroju, expat >= 2.4.1) (vedome potlaceni nalezu banditu, viz SECURITY.md)
    root = ET.fromstring(r.content)  # nosec B314
    dumps = []
    for d in root.iter():
        if _local(d.tag) != "dump":
            continue
        odkaz = _text(d, "odkaz") or ""
        m = re.search(r"dump_(\d{4})_(\d{2})(?:_(\d{2}))?", odkaz)
        den = _text(d, "den") or (m.group(3) if m else None)
        dumps.append({
            "rok": int(_text(d, "rok") or (m.group(1) if m else 0)),
            "mesic": int(_text(d, "mesic") or (m.group(2) if m else 0)),
            "den": int(den) if den else None,  # index obsahuje i denni prirustky, ne jen mesicni dumpy
            "odkaz": odkaz,
            "velikost": int(_text(d, "velikostDumpu") or 0),
            "dokonceny": _text(d, "dokoncenyMesic") == "1",
        })
    return dumps


def vyber_dumpy(dumps, mesicu):
    """Poslednich `mesicu` mesicu: mesicni dump, a jen kde mesicni chybi, denni prirustky toho mesice.
    Vraci [(dump_id, dump)] serazene od nejstarsiho; dump_id je unikatni (2025_03 nebo 2026_11_12)."""
    mesice = sorted({(d["rok"], d["mesic"]) for d in dumps if d["rok"] and d["mesic"]})[-mesicu:] if mesicu > 0 else []
    out = []
    for rok, mes in mesice:
        cele = [d for d in dumps if (d["rok"], d["mesic"]) == (rok, mes) and not d["den"]]
        if cele:
            out.append((f"{rok}_{mes:02d}", cele[-1]))
        else:
            out += [(f"{rok}_{mes:02d}_{d['den']:02d}", d) for d in sorted(
                (d for d in dumps if (d["rok"], d["mesic"]) == (rok, mes) and d["den"]), key=lambda d: d["den"])]
    return out


def fetch_dump(dump):
    name = "smlouvy_" + (os.path.basename(dump.get("odkaz") or "") or f"dump_{dump['rok']}_{dump['mesic']:02d}.xml")
    dest = os.path.join(CACHE_DIR, name)
    max_age = None if dump["dokonceny"] else 24
    mb = dump["velikost"] >> 20
    if not os.path.exists(dest):
        log("Scout", f"Registr smluv {dump['mesic']:02d}/{dump['rok']}: stahuji ~{mb} MB, chvili to potrva")
    return download(dump["odkaz"], dest, max_age_hours=max_age)


def iter_smlouvy(xml_path):
    """Streamovane cteni dumpu, vraci dict pro kazdou platnou verzi smlouvy."""
    # bezpecnost: viz SECURITY.md (vedome potlaceni nalezu banditu, viz SECURITY.md)
    for event, el in ET.iterparse(xml_path, events=("end",)):  # nosec B314
        if _local(el.tag) != "zaznam":
            continue
        try:
            platny = _text(el, "platnyZaznam")
            if platny is not None and platny != "1":
                continue
            ident = _child(el, "identifikator")
            sid = _text(ident, "idSmlouvy") if ident is not None else None
            vid = _text(ident, "idVerze") if ident is not None else None
            sm = _child(el, "smlouva")
            if sm is None:
                continue
            subj = _child(sm, "subjekt")
            strany = []
            for c in sm:
                if _local(c.tag) == "smluvniStrana":
                    strany.append({"ico": clean_ico(_text(c, "ico")), "nazev": _text(c, "nazev")})
            yield {
                "id": sid or vid,
                "predmet": _text(sm, "predmet"),
                "datum_uzavreni": _text(sm, "datumUzavreni"),
                "hodnota_bez_dph": to_float(_text(sm, "hodnotaBezDph")),
                "hodnota_s_dph": to_float(_text(sm, "hodnotaVcetneDph")),
                "zadavatel_ico": clean_ico(_text(subj, "ico")) if subj is not None else None,
                "zadavatel_nazev": _text(subj, "nazev") if subj is not None else None,
                "url": _text(el, "odkaz"),
                "strany": strany,
            }
        finally:
            el.clear()


def is_relevant(sml, keywords_norm, ico_set):
    """Relevantni = protistranou je znamy konkurent (ICO z RVZ) nebo predmet obsahuje klicove slovo oboru."""
    if ico_set:
        for s in sml["strany"]:
            if s["ico"] and s["ico"] in ico_set:
                return True
    p = " " + norm(sml["predmet"]) + " "
    return any(k in p for k in keywords_norm)
