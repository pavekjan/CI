"""Registr verejnych zakazek (RVZ) - otevrena data ISVZ (NEN, VVZ, Tender arena, TENDERMARKET).

Bez registrace. MMR publikuje mesicni ZIP soubory s JSON daty vzdy k ~5. dni nasledujiciho mesice:
    https://isvz.nipez.cz/sites/default/files/content/opendata-rvz/VZ-MM-YYYY.zip
Data zacinaji unorem 2024. Struktura JSON se meni s verzi dokumentace (2.x), proto
Extractor cte pole heuristicky (viz extractor.py) a prikaz `inspect` ukaze skutecne klice.
"""
import io
import json
import os
import zipfile

from ..util import CACHE_DIR, download, log

try:
    import ijson  # volitelne: setri pamet u velkych souboru
except ImportError:  # pragma: no cover
    ijson = None


def month_url(base, year, month, kategorie="VZ"):
    return f"{base}{kategorie}-{month:02d}-{year}.zip"


def fetch_month(base, year, month, kategorie="VZ", current=False):
    url = month_url(base, year, month, kategorie)
    dest = os.path.join(CACHE_DIR, f"rvz_{kategorie}-{month:02d}-{year}.zip")
    # posledni mesice MMR pregenerovava -> cache max 7 dni; starsi drzime
    return download(url, dest, max_age_hours=24 * 7 if current else None)


def _backend():
    if ijson is not None and "yajl2" in str(getattr(ijson, "backend", "")):
        return f"ijson/{ijson.backend}"
    return "proudove (json)"


def _iter_json_stream(fobj):
    """Projde JSON soubor a vrati jednotlive zaznamy (dict) - zvladne pole, objekt s polem i JSONL."""
    head = fobj.read(4096)
    fobj.seek(0)
    text_head = head.lstrip()
    if text_head.startswith(b"\xef\xbb\xbf"):
        text_head = text_head[3:].lstrip()
    first = text_head[:1]

    # JSON Lines?
    first_line = head.split(b"\n", 1)[0].strip()
    if first == b"{" and b"\n" in head:
        try:
            json.loads(first_line.decode("utf-8-sig"))
            for line in io.TextIOWrapper(fobj, encoding="utf-8-sig"):
                line = line.strip()
                if line:
                    yield json.loads(line)
            return
        except ValueError:
            fobj.seek(0)

    if ijson is not None and "yajl2" in str(getattr(ijson, "backend", "")):  # jen rychly C backend, jinak vlastni cteni
        if first == b"[":
            yield from ijson.items(fobj, "item", use_float=True)
            return
        # objekt: najdi prvni pole objektu, ktere obsahuje objekty
        prefix = None
        for pfx, event, _ in ijson.parse(fobj):
            if event == "start_map" and pfx.endswith(".item"):
                prefix = pfx
                break
        fobj.seek(0)
        if prefix:
            yield from ijson.items(fobj, prefix, use_float=True)
            return
        fobj.seek(0)

    # bez ijson: vlastni proudove cteni (nikdy nenacitat cely soubor o velikosti GB do pameti)
    yield from _iter_stdlib(fobj)


def _iter_stdlib(fobj, blok=1 << 20, max_zaznam=64 << 20):
    """Proudove cteni pole zaznamu jen se standardni knihovnou: najde prvni pole objektu ('[' a za nim '{')
    a pak po jednom dekoduje objekty pomoci json.raw_decode. Pamet = jen par MB bez ohledu na velikost souboru."""
    text = io.TextIOWrapper(fobj, encoding="utf-8-sig")
    dec = json.JSONDecoder()
    buf, konec = "", False

    def docti():
        nonlocal buf, konec
        kus = text.read(blok)
        if kus:
            buf += kus
        else:
            konec = True

    # 1) zacatek pole se zaznamy
    while True:
        i = 0
        nalez = -1
        while True:
            j = buf.find("[", i)
            if j < 0:
                break
            k = j + 1
            while k < len(buf) and buf[k] in " \t\r\n":
                k += 1
            if k < len(buf) and buf[k] == "{":
                nalez = k
                break
            if k >= len(buf):
                break  # nevime, co nasleduje -> docist
            i = j + 1
        if nalez >= 0:
            buf = buf[nalez:]
            break
        if konec:
            return
        if len(buf) > max_zaznam:
            buf = buf[-16:]
        docti()
    # 2) objekty jeden po druhem (pozice v bufferu, ne kopirovani retezce po kazdem zaznamu)
    pos = 0
    bile = " \t\r\n,"
    while True:
        while pos < len(buf) and buf[pos] in bile:
            pos += 1
        if pos >= len(buf):
            if konec:
                return
            buf, pos = buf[pos:], 0
            docti()
            continue
        if buf[pos] != "{":
            return  # konec pole
        try:
            obj, end = dec.raw_decode(buf, pos)
        except json.JSONDecodeError:
            if konec or len(buf) - pos > max_zaznam:
                raise
            buf, pos = buf[pos:], 0
            docti()
            continue
        if isinstance(obj, dict):
            yield obj
        pos = end


def _records_from_obj(data):
    if isinstance(data, list):
        for x in data:
            if isinstance(x, dict):
                yield x
        return
    if isinstance(data, dict):
        lists = [v for v in data.values() if isinstance(v, list) and v and isinstance(v[0], dict)]
        if lists:
            for lst in lists:
                yield from lst
        else:
            yield data


def iter_records(zip_path):
    """Vsechny zaznamy ze vsech JSON souboru v ZIPu."""
    with zipfile.ZipFile(zip_path) as z:
        for name in z.namelist():
            if not name.lower().endswith((".json", ".jsonl")):
                continue
            size = z.getinfo(name).file_size
            log("Scout", f"  cteni {name} ({size / 1e6:.0f} MB rozbaleno, parser: {_backend()})")
            with z.open(name) as raw:
                # ijson potrebuje seek -> nacteme do docasneho souboru jen kdyz je to nutne
                buf = _seekable(raw)
                yield from _iter_json_stream(buf)


def _seekable(raw):
    import tempfile
    tmp = tempfile.TemporaryFile()
    while True:
        chunk = raw.read(1 << 20)
        if not chunk:
            break
        tmp.write(chunk)
    tmp.seek(0)
    return tmp


def first_record(zip_path):
    for rec in iter_records(zip_path):
        return rec
    return None


def log_missing(year, month):
    log("Scout", f"RVZ {month:02d}/{year}: soubor zatim neni zverejnen (MMR publikuje ~5. dne dalsiho mesice)")
