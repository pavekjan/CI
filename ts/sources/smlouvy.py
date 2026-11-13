"""Registr smluv - otevrena data (bez registrace).

https://data.smlouvy.gov.cz/index.xml  -> seznam mesicnich dumpu
https://data.smlouvy.gov.cz/dump_YYYY_MM.xml -> vsechny smlouvy zverejnene v mesici
Dumpy jsou velke (stovky MB), proto se ctou streamovane (iterparse) a ukladaji se
jen smlouvy relevantni pro obor nebo pro zname dodavatele/zadavatele.
"""
import os
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
    root = ET.fromstring(r.content)
    dumps = []
    for d in root.iter():
        if _local(d.tag) != "dump":
            continue
        dumps.append({
            "rok": int(_text(d, "rok") or 0),
            "mesic": int(_text(d, "mesic") or 0),
            "odkaz": _text(d, "odkaz"),
            "velikost": int(_text(d, "velikostDumpu") or 0),
            "dokonceny": _text(d, "dokoncenyMesic") == "1",
        })
    return dumps


def fetch_dump(dump):
    name = f"smlouvy_dump_{dump['rok']}_{dump['mesic']:02d}.xml"
    dest = os.path.join(CACHE_DIR, name)
    max_age = None if dump["dokonceny"] else 24
    mb = dump["velikost"] >> 20
    if not os.path.exists(dest):
        log("Scout", f"Registr smluv {dump['mesic']:02d}/{dump['rok']}: stahuji ~{mb} MB, chvili to potrva")
    return download(dump["odkaz"], dest, max_age_hours=max_age)


def iter_smlouvy(xml_path):
    """Streamovane cteni dumpu, vraci dict pro kazdou platnou verzi smlouvy."""
    for event, el in ET.iterparse(xml_path, events=("end",)):
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
