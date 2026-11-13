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


def je_tajne(k):
    """Klice API a tokeny: nikdy do config.json v gitu."""
    return k.endswith(("_api_key", "_token"))


LOCAL_CONFIG = os.path.join(ROOT, "config.local.json")  # osobni nastaveni a klice, NIKDY do gitu


def nacti_env_soubor(path=None):
    """Nacte .env (KLIC=hodnota) do promennych prostredi. Soubor .env je v .gitignore."""
    path = path or os.path.join(ROOT, ".env")
    if not os.path.exists(path):
        return
    with open(path, encoding="utf-8") as f:
        for radek in f:
            radek = radek.strip()
            if not radek or radek.startswith("#") or "=" not in radek:
                continue
            k, v = radek.split("=", 1)
            v = v.strip().strip('"').strip("'")
            if k.strip() and v:
                os.environ.setdefault(k.strip(), v)


def _presun_tajemstvi(path, cfg):
    """Starsi verze ukladaly klice primo do config.json, ktery je v gitu. Presuneme je do
    config.local.json (mimo git) a v config.json je smazeme (pravidlo 1: tajemstvi ne do repozitare)."""
    nalezene = {k: v for k, v in cfg.items() if je_tajne(k) and v}
    if not nalezene:
        return
    lokal = {}
    if os.path.exists(LOCAL_CONFIG):
        with open(LOCAL_CONFIG, encoding="utf-8") as f:
            lokal = json.load(f)
    for k, v in nalezene.items():
        lokal.setdefault(k, v)
    with open(LOCAL_CONFIG, "w", encoding="utf-8") as f:
        json.dump(lokal, f, ensure_ascii=False, indent=2)
    for k in nalezene:
        cfg[k] = ""
    with open(path, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
    print("Bezpecnost: API klice presunuty z config.json do config.local.json (ten se do gitu nenahrava).")


def load_config(path=None):
    path = path or os.path.join(ROOT, "config.json")
    with open(path, encoding="utf-8") as f:
        cfg = json.load(f)
    if os.path.abspath(path) == os.path.join(ROOT, "config.json"):
        _presun_tajemstvi(path, dict(cfg))
        for k in [k for k in cfg if je_tajne(k)]:
            cfg[k] = ""
    if os.path.exists(LOCAL_CONFIG):
        with open(LOCAL_CONFIG, encoding="utf-8") as f:
            cfg.update({k: v for k, v in json.load(f).items() if v not in (None, "")})
    nacti_env_soubor()
    # na serveru se klice zadavaji jako tajne promenne prostredi (nikdy ne do config.json na GitHubu)
    for env, k in (("HLIDAC_TOKEN", "hlidac_token"), ("EXA_API_KEY", "exa_api_key"),
                   ("ANTHROPIC_MODEL", "anthropic_model"), ("LLM_POSKYTOVATEL", "llm_poskytovatel")):
        if os.environ.get(env):
            cfg[k] = os.environ[env]
    from . import llm  # klice vsech poskytovatelu AI (OPENAI_API_KEY, GROQ_API_KEY, ...)
    llm.env_do_cfg(cfg)
    # LLM_MODEL a LLM_URL plati pro vybraneho poskytovatele
    prov = cfg.get("llm_poskytovatel") or "anthropic"
    for env, pripona in (("LLM_MODEL", "model"), ("LLM_URL", "url")):
        if os.environ.get(env):
            cfg[f"{prov}_{pripona}"] = os.environ[env]
    return cfg


LOG_SINKS = []  # server si sem prida funkci a posila log do webove aplikace


def log(agent, msg):
    ts = datetime.now().strftime("%H:%M:%S")
    line = f"[{ts}] {agent:<12} {msg}"
    print(line, flush=True)
    for sink in LOG_SINKS:
        try:
            sink(line)
        except Exception:
            pass


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
    d = None
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", s)
    if m:
        try:
            d = date(int(m[1]), int(m[2]), int(m[3]))
        except ValueError:
            return None
    else:
        m = re.match(r"(\d{1,2})\.\s*(\d{1,2})\.\s*(\d{4})", s)
        if m:
            try:
                d = date(int(m[3]), int(m[2]), int(m[1]))
            except ValueError:
                return None
    if d and not (2000 <= d.year <= 2045):  # preklepy v datech (napr. rok 0217)
        return None
    return d


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
