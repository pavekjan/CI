"""Spolecne pomucky: konfigurace, HTTP s cache, normalizace textu, logovani."""
import json
import os
import re
import sys
import time
import unicodedata
from datetime import datetime, date

import requests

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(ROOT, "data")
CACHE_DIR = os.path.join(DATA_DIR, "cache")
OUT_DIR = os.path.join(ROOT, "vystupy")
USER_AGENT = "TenderScope/0.1 (studentsky prototyp competitive intelligence; python-requests)"

for _d in (DATA_DIR, CACHE_DIR, OUT_DIR):
    os.makedirs(_d, exist_ok=True)

# Windows konzole: aby se cestina nerozbila
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass


def load_config(path=None):
    path = path or os.path.join(ROOT, "config.json")
    with open(path, encoding="utf-8") as f:
        cfg = json.load(f)
    if os.environ.get("HLIDAC_TOKEN"):
        cfg["hlidac_token"] = os.environ["HLIDAC_TOKEN"]
    return cfg


def log(agent, msg):
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] {agent:<12} {msg}", flush=True)


def norm(s):
    """Mala pismena, bez diakritiky, jen alfanumericke znaky a mezery."""
    if s is None:
        return ""
    s = unicodedata.normalize("NFKD", str(s))
    s = "".join(c for c in s if not unicodedata.combining(c)).lower()
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


def nkey(s):
    """Normalizovany klic slovniku (bez mezer) pro heuristiky."""
    return norm(s).replace(" ", "")


def to_float(v):
    if v is None or isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip().replace("\xa0", "").replace(" ", "")
    if not s:
        return None
    if "," in s and "." in s:
        s = s.replace(".", "").replace(",", ".")
    else:
        s = s.replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None


def parse_date(v):
    """Vrati date nebo None z ruznych formatu (ISO, 'YYYY-MM-DDTHH:MM', 'DD.MM.YYYY')."""
    if not v:
        return None
    if isinstance(v, (date, datetime)):
        return v if isinstance(v, date) and not isinstance(v, datetime) else v.date()
    s = str(v).strip()
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", s)
    if m:
        try:
            return date(int(m[1]), int(m[2]), int(m[3]))
        except ValueError:
            return None
    m = re.match(r"(\d{1,2})\.\s*(\d{1,2})\.\s*(\d{4})", s)
    if m:
        try:
            return date(int(m[3]), int(m[2]), int(m[1]))
        except ValueError:
            return None
    return None


def ico_valid(ico):
    """Kontrola IČO pomoci kontrolni cislice (modulo 11)."""
    if not ico or not re.fullmatch(r"\d{8}", str(ico)):
        return False
    d = [int(c) for c in str(ico)]
    s = sum(d[i] * (8 - i) for i in range(7))
    r = s % 11
    check = 1 if r == 0 else (0 if r == 1 else 11 - r)
    return check == d[7]


def clean_ico(v):
    if v is None:
        return None
    s = re.sub(r"\D", "", str(v))
    if not s or len(s) > 8:
        return None
    return s.zfill(8)


_session = None


def session():
    global _session
    if _session is None:
        _session = requests.Session()
        _session.headers["User-Agent"] = USER_AGENT
    return _session


def http_get(url, *, params=None, headers=None, timeout=60, retries=3, stream=False):
    last = None
    for i in range(retries):
        try:
            r = session().get(url, params=params, headers=headers, timeout=timeout, stream=stream)
            if r.status_code in (429, 502, 503, 504):
                last = f"HTTP {r.status_code}"
                time.sleep(2 * (i + 1))
                continue
            return r
        except requests.RequestException as e:
            last = str(e)
            time.sleep(2 * (i + 1))
    raise RuntimeError(f"Nepodarilo se stahnout {url}: {last}")


def download(url, dest, max_age_hours=None, agent="Scout"):
    """Stahne soubor na disk (streamovane). Pokud existuje a je dost cerstvy, pouzije cache.
    Vraci cestu nebo None pri 404."""
    if os.path.exists(dest) and os.path.getsize(dest) > 0:
        age_h = (time.time() - os.path.getmtime(dest)) / 3600
        if max_age_hours is None or age_h < max_age_hours:
            log(agent, f"cache: {os.path.basename(dest)}")
            return dest
    r = http_get(url, stream=True, timeout=120)
    if r.status_code == 404:
        return None
    if r.status_code != 200:
        raise RuntimeError(f"{url} vratil HTTP {r.status_code}")
    total = int(r.headers.get("Content-Length") or 0)
    tmp = dest + ".part"
    got = 0
    last_print = 0
    with open(tmp, "wb") as f:
        for chunk in r.iter_content(chunk_size=1 << 20):
            f.write(chunk)
            got += len(chunk)
            if got - last_print > 25 << 20:
                last_print = got
                pct = f" ({100 * got // total} %)" if total else ""
                log(agent, f"  stahuji {os.path.basename(dest)}: {got >> 20} MB{pct}")
    os.replace(tmp, dest)
    log(agent, f"stazeno {os.path.basename(dest)} ({got >> 20} MB)")
    return dest


def months_back(n, today=None):
    """Seznam (rok, mesic) za poslednich n mesicu vcetne aktualniho, od nejstarsiho."""
    today = today or date.today()
    y, m = today.year, today.month
    out = []
    for _ in range(n):
        out.append((y, m))
        m -= 1
        if m == 0:
            y, m = y - 1, 12
    return list(reversed(out))


NUTS_KRAJ = {
    "CZ010": "Hlavní město Praha", "CZ020": "Středočeský", "CZ031": "Jihočeský", "CZ032": "Plzeňský",
    "CZ041": "Karlovarský", "CZ042": "Ústecký", "CZ051": "Liberecký", "CZ052": "Královéhradecký",
    "CZ053": "Pardubický", "CZ063": "Vysočina", "CZ064": "Jihomoravský", "CZ071": "Olomoucký",
    "CZ072": "Zlínský", "CZ080": "Moravskoslezský",
}


def nuts_to_kraj(nuts):
    if not nuts:
        return "neuvedeno"
    n = str(nuts).upper().replace(" ", "")
    for k, v in NUTS_KRAJ.items():
        if n.startswith(k):
            return v
    if n in ("CZ0", "CZ"):
        return "celá ČR"
    return n
