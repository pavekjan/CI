"""TenderScope - webova aplikace (backend). Jen standardni knihovna Pythonu + requests.

    python server.py            # realna data (data/tenderscope.db)
    python server.py --demo     # umela data, bez internetu
    python server.py --port 8765 --neotvirat

Frontend (TypeScript/React) je predkompilovany ve web/dist. API:
    GET  /api/stav                 stav databaze
    GET  /api/hledat?q=...         hledani firmy (nazev nebo IČO)
    GET  /api/firma/<ico>          profil konkurenceschopnosti
    GET  /api/trh?segment=...      prehled trhu
    POST /api/aktualizovat         {"rezim": "rychle" | "plny"} - spusti agenty na pozadi
    GET  /api/beh                  prubeh aktualizace (log)
    POST /api/onboarding/start     {"ico", "web"} - Recon + Faze 1 (4 otazky)
    POST /api/onboarding/dokoncit  {"ico", "odpovedi"} - Faze 2 (company_profile) + Day-0 zpravodaj
    GET  /api/onboarding           seznam profilu;  GET /api/onboarding/<ico> ulozeny stav + zpravodaj
    POST /api/onboarding/<ico>/profil  {"profil"} - ulozit upraveny profil, prepocitat zpravodaj
    GET  /api/vhodnost/<ico>?zakazka=<id>  dotaznik vhodnosti jedne zakazky
"""
import argparse
import hmac
import json
import re
import secrets
import mimetypes
import os
import sys
import threading
import traceback
import webbrowser
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlparse

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

from ts import api, bezpecnost, onboarding, scout, verifier  # noqa: E402
from ts.db import connect  # noqa: E402
from ts.util import DATA_DIR, LOCAL_CONFIG, LOG_SINKS, load_config, log, nacti_env_soubor  # noqa: E402

DIST = os.path.join(ROOT, "web", "dist")
STATE = {"demo": False, "db": os.path.join(DATA_DIR, "tenderscope.db"), "cfg": None}
JOB = {"bezi": False, "rezim": None, "log": [], "chyba": None, "zacatek": None, "konec": None}
JOB_LOCK = threading.Lock()
EXPORTS = {}  # ico -> (nazev souboru, bytes zipu)

nacti_env_soubor()  # .env (mimo git) -> promenne prostredi, jeste pred ctenim TS_ADMIN_HESLO

# ---------------------------------------------------------------------------------------------
# BEZPECNOST (viz SECURITY.md)
# Online (verejna) verze: zapne se TS_VEREJNE=1, nastavenim TS_ADMIN_HESLO, nebo samo, kdyz server
# posloucha na jine nez lokalni adrese. Pak smi kdokoli prohlizet, ale aktualizaci dat, klice,
# diagnostiku a placena API (Claude, Exa) pouzije jen spravce s heslem (hlavicka X-Admin-Heslo).
# Pri jakekoli chybe kontroly se pristup ZAMITNE (fail closed).
# ---------------------------------------------------------------------------------------------
SEC = {
    "verejne": (os.environ.get("TS_VEREJNE", "").lower() in ("1", "true", "ano")) or bool(os.environ.get("TS_ADMIN_HESLO")),
    "heslo": os.environ.get("TS_ADMIN_HESLO", ""),
    "proxy_hops": int(os.environ.get("TS_PROXY_HOPS") or 1),  # Render = 1 proxy pred aplikaci
    "hosty": {h.strip().lower() for h in (os.environ.get("TS_POVOLENE_HOSTY") or "").split(",") if h.strip()},
}
NEPOVOLENO = "Na online verzi to může jen správce. Zadejte admin heslo v záložce Data."
MAX_TELO = 512 * 1024          # max. velikost JSON tela pozadavku
LIMIT_API = bezpecnost.RateLimiter(int(os.environ.get("TS_LIMIT_ZA_MINUTU") or 120), 60)
LIMIT_DRAHE = bezpecnost.RateLimiter(int(os.environ.get("TS_LIMIT_DRAHE_ZA_MINUTU") or 10), 60)
LIMIT_HESLO = bezpecnost.RateLimiter(5, 15 * 60)   # 5 chybnych hesel za 15 minut na IP
# denni strop volani AI (Claude, OpenAI, Gemini...) pro celou aplikaci - ochrana penezenky
LLM_DEN = bezpecnost.DenniLimit(int(os.environ.get("TS_LIMIT_LLM_DEN") or os.environ.get("TS_LIMIT_CLAUDE_DEN") or 30))
EXA_DEN = bezpecnost.DenniLimit(int(os.environ.get("TS_LIMIT_EXA_DEN") or 40))
MAX_EXPORTU = 20


def je_admin(headers, ip="?"):
    """Fail closed: kdyz cokoli selze, vraci False."""
    try:
        if not SEC["verejne"]:
            return True
        if not SEC["heslo"]:
            return False
        h = headers.get("X-Admin-Heslo")
        if not h:
            return False
        ok = hmac.compare_digest(unquote(h).encode("utf-8"), SEC["heslo"].encode("utf-8"))
        if not ok:
            log("Bezpecnost", f"chybne admin heslo z {ip}")
        return ok
    except Exception:
        log("Bezpecnost", "chyba pri kontrole opravneni -> zamitnuto")
        return False


def cfg_pro(admin):
    """Na verejne verzi bez hesla se nepouzivaji placena API (AI, Exa) - onboarding jede na pravidla."""
    if admin:
        return STATE["cfg"]
    return dict(STATE["cfg"], llm_vypnuto=True, exa_api_key="")


def _nahled(k):
    return (k[:5] + "…") if k and len(k) > 12 else ("✓" if k else "")


def nastaveni_get(admin=True):
    from ts import llm
    c = STATE["cfg"]
    key = c.get("exa_api_key") or ""
    skryt = SEC["verejne"] and not admin  # navstevnik nepotrebuje vedet nic o klicich, adresach ani cestach
    prov = llm.poskytovatel(c)
    poskytovatele = []
    for pid, p in llm.POSKYTOVATELE.items():
        k = (c.get(p["klic"]) or "") if p["klic"] else ""
        poskytovatele.append({
            "id": pid, "nazev": p["nazev"], "web": p["web"], "potrebuje_klic": bool(p["klic"]) and not p.get("klic_volitelny"),
            "ma_klic_pole": bool(p["klic"]), "vlastni_url": bool(p.get("vlastni_url")), "env": p["env"],
            "klic_nastaven": bool(k), "klic_nahled": "" if skryt else _nahled(k),
            "model": c.get(f"{pid}_model") or p["model"], "model_vychozi": p["model"],
            "url": "" if skryt else ((c.get(f"{pid}_url") if p.get("vlastni_url") else None) or p["url"]),
            "zdarma": bool(p.get("zdarma")), "limit": p.get("limit", ""), "pozn": p.get("pozn", ""),
            "soukromi_ok": bool(p.get("soukromi_ok")), "potrebuje_ucet": bool(p.get("ucet")),
            "ucet": "" if skryt else (c.get(f"{pid}_ucet") or ""),
        })
    aktivni = llm.nastaveni(c)
    return {"obsidian_vault": "" if skryt else (c.get("obsidian_vault") or ""), "exa_api_key_nastaven": bool(key),
            "exa_api_key_nahled": "" if skryt else _nahled(key),
            "ai": {"poskytovatel": prov, "pripraveno": bool(aktivni), "model": aktivni["model"] if aktivni else None,
                   "poskytovatele": poskytovatele, "anthropic_sdk": llm.dostupne()},
            "verejne": SEC["verejne"], "admin": admin,
            "limity": {"ai_dnes": LLM_DEN.pouzito, "ai_max": LLM_DEN.limit,
                       "exa_dnes": EXA_DEN.pouzito, "exa_max": EXA_DEN.limit}}


def _ai_hodnoty(body):
    """Validace nastaveni AI z formulare. Vraci {klic_v_configu: hodnota}."""
    from ts import llm
    out = {}
    prov = body.get("llm_poskytovatel")
    if prov is not None:
        if prov not in llm.POSKYTOVATELE:
            raise bezpecnost.ChybaVstupu("Neznámý poskytovatel AI.")
        out["llm_poskytovatel"] = prov
    prov = prov or llm.poskytovatel(STATE["cfg"])
    p = llm.POSKYTOVATELE[prov]
    if body.get("llm_klic"):
        if not p["klic"]:
            raise bezpecnost.ChybaVstupu(f"{p['nazev']} klíč nepotřebuje.")
        out[p["klic"]] = bezpecnost.klic_api(body["llm_klic"], "API klíč")
    if body.get("llm_model"):
        out[f"{prov}_model"] = bezpecnost.model(body["llm_model"])
    if body.get("llm_url") is not None and p.get("vlastni_url"):
        out[f"{prov}_url"] = bezpecnost.over_api_url(body["llm_url"], SEC["verejne"])
    if body.get("llm_ucet") and p.get("ucet"):
        ucet = bezpecnost.text(body["llm_ucet"], 40, "Account ID").lower()
        if not re.fullmatch(llm.UCET_RE, ucet):
            raise bezpecnost.ChybaVstupu("Account ID má 32 znaků (0-9, a-f), najdete ho v přehledu účtu Cloudflare.")
        out[f"{prov}_ucet"] = ucet
    return out


def nastaveni_set(body):
    """Klice se ukladaji do config.local.json (je v .gitignore), nikdy do config.json v gitu."""
    hodnoty = _ai_hodnoty(body)
    if "obsidian_vault" in body and not SEC["verejne"]:  # server nezapisuje do libovolnych slozek
        hodnoty["obsidian_vault"] = bezpecnost.text(body.get("obsidian_vault"), 500, "cesta k Obsidianu")
    if body.get("exa_api_key"):
        hodnoty["exa_api_key"] = bezpecnost.klic_api(body.get("exa_api_key"), "Exa klíč")
    lokal = {}
    if os.path.exists(LOCAL_CONFIG):
        with open(LOCAL_CONFIG, encoding="utf-8") as f:
            lokal = json.load(f)
    lokal.update(hodnoty)
    STATE["cfg"].update(hodnoty)
    with open(LOCAL_CONFIG, "w", encoding="utf-8") as f:
        json.dump(lokal, f, ensure_ascii=False, indent=2)
    log("Bezpecnost", "nastaveni zmeneno: " + (", ".join(hodnoty) or "nic"))  # jen nazvy poli, nikdy hodnoty
    return nastaveni_get()


def ai_akce(body, akce):
    """Nacist modely / vyzkouset AI s hodnotami z formulare (bez ulozeni)."""
    from ts import llm
    cfg = dict(STATE["cfg"], **_ai_hodnoty(body))
    prov = llm.poskytovatel(cfg)
    n = llm.nastaveni(cfg, prov)
    if not n:
        p = llm.POSKYTOVATELE[prov]
        if p.get("vlastni_url") and not (cfg.get(f"{prov}_url") or p["url"]):
            chybi = "adresu API"
        elif p.get("ucet") and not cfg.get(f"{prov}_ucet"):
            chybi = "Account ID" + ("" if cfg.get(p["klic"]) else " a API token")
        else:
            chybi = "API klíč"
        raise bezpecnost.ChybaVstupu(f"Nejdřív vyplňte {chybi} pro {p['nazev']}.")
    try:
        if akce == "modely":
            return {"ok": True, "modely": llm.modely(n)}
        if not LLM_DEN.vezmi():
            raise bezpecnost.ChybaVstupu("Denní limit volání AI je vyčerpán.")
        return llm.vyzkousej(n)
    except bezpecnost.ChybaVstupu:
        raise
    except Exception as e:
        return {"ok": False, "chyba": llm.chyba_text(e)}


def export_obsidian(ico, zapsat, cfg):
    from ts import obsidian
    con = connect(STATE["db"])
    try:
        online = not STATE["demo"]
        p = api.profil(con, ico, cfg, online=online)
        exa = []
        key = cfg.get("exa_api_key")
        if key and online and p["nazev"] != p["ico"] and EXA_DEN.vezmi() and EXA_DEN.vezmi():
            exa = obsidian.exa_search(key, f'"{p["nazev"]}" veřejné zakázky', 6) + obsidian.exa_search(key, f'{p["nazev"]} firma novinky', 4)
        v = obsidian.export_firma(con, p, cfg, exa)
    finally:
        con.close()
    name = f"TenderScope_{obsidian.safe(p['nazev'], 40).replace(' ', '_')}.zip"
    EXPORTS.pop(ico, None)
    EXPORTS[ico] = (name, v.zip_bytes())
    while len(EXPORTS) > MAX_EXPORTU:  # ochrana pameti serveru
        EXPORTS.pop(next(iter(EXPORTS)))
    out = {"ok": True, "nazev": p["nazev"], "poznamek": len(v.files), "zdroju": v.n_src, "exa": len(exa),
           "zip": f"/api/export-zip/{ico}", "zapsano": None}
    vault = cfg.get("obsidian_vault")
    if zapsat and vault:
        if not os.path.isdir(vault):
            out["chyba_zapisu"] = f"Složka trezoru neexistuje: {vault}"
        else:
            v.write_dir(vault)
            out["zapsano"] = os.path.join(vault, obsidian.ROOT_DIR)
    return out


def _sink(line):
    # log aktualizace je videt v aplikaci: bezpecnostni zaznamy (IP adresy) do nej nepatri, jen do konzole
    # ani co si kdo zadal v onboardingu (IČO firmy) - log vidi vsichni navstevnici online verze
    if any(f"] {a:<12} " in line for a in ("Bezpecnost", "Server", "Onboarding", "LLM")):
        return
    JOB["log"].append(line)
    if len(JOB["log"]) > 400:
        del JOB["log"][:100]


LOG_SINKS.append(_sink)


def run_update(rezim):
    try:
        if STATE["demo"]:
            import demo
            log("Orchestrator", "DEMO: generuji umela data a poustim agenty...")
            demo.build_demo_db(STATE["db"])
        else:
            cfg = dict(STATE["cfg"])
            cfg["obor"] = "vse"
            if rezim == "rychle":
                cfg.update({"mesice": 3, "smlouvy_mesice": 0, "ares_max_firem": 30})
            else:
                cfg.update({"mesice": cfg.get("mesice", 12), "smlouvy_mesice": cfg.get("smlouvy_mesice", 3), "ares_max_firem": 100})
            con = connect(STATE["db"])
            from ts.orchestrator import _step
            stats = {}
            _step(con, "Scout+Extractor: RVZ/NEN/Věstník", scout.scout_rvz, stats, con, cfg, None)
            _step(con, "Scout: Registr smluv", scout.scout_smlouvy, stats, con, cfg)
            _step(con, "Scout: ARES", scout.scout_ares, stats, con, cfg)
            _step(con, "Verifier", verifier.run, stats, con)
            _step(con, "Indexer", api.rebuild_index, stats, con)
            con.close()
        log("Orchestrator", "HOTOVO - data jsou aktualni")
    except Exception as e:
        traceback.print_exc()
        JOB["chyba"] = str(e)
        log("Orchestrator", f"CHYBA: {e}")
    finally:
        JOB["bezi"] = False
        JOB["konec"] = datetime.now().isoformat(timespec="seconds")


def _orez(o, n=3):
    """Zkrati dlouhe seznamy (dokumenty, historie), aby vypis zustal citelny."""
    if isinstance(o, dict):
        return {k: _orez(v, n) for k, v in o.items()}
    if isinstance(o, list):
        return [_orez(x, n) for x in o[:n]] + ([f"... a dalsich {len(o) - n}"] if len(o) > n else [])
    return o


def diagnostika_struktura(files, ico=None, max_zaznamu=4000):
    """Kde v zaznamech lezi CPV, ceny a dodavatele (cetnost cest klicu) + ukazkovy zaznam s danym IČO."""
    import json as _json
    from collections import Counter
    from ts import extractor
    from ts.sources import rvz
    from ts.util import nkey
    cesty = Counter()
    ukazky = []
    n = 0
    hled = ico and str(ico).strip()
    for f in reversed(files):
        for rec in rvz.iter_records(f):
            n += 1
            if n <= max_zaznamu:
                for path, val in extractor.walk(rec):
                    p = "/".join(nkey(x) for x in path)
                    sv = str(val)
                    if any(w in p for w in ("cpv", "cena", "hodnot", "dodavatel", "ucastn", "nabid", "vitez", "smlouv", "ico", "datum")) \
                            or extractor.CPV_FULL.match(sv.strip()):
                        cesty[".".join(path)] += 1
            if hled and len(ukazky) < 2 and hled in _json.dumps(rec, ensure_ascii=False):
                zak, vit, uc = extractor.extract(rec)
                ukazky.append({"soubor": os.path.basename(f), "zaznam": _orez(rec),
                               "extrahovano": {"zakazka": zak, "vitezove": vit, "ucastnici": uc}})
            if n > max_zaznamu and (not hled or len(ukazky) >= 2 or n > 400000):
                break
        if n > max_zaznamu and (not hled or len(ukazky) >= 2):
            break
    return {"prohledano_zaznamu": n, "cesty_klicu (z prvnich %d)" % max_zaznamu: [f"{c:>6}x  {p}" for p, c in cesty.most_common(120)],
            "hledane_ico": hled, "zaznamy_s_ico": ukazky}


def diagnostika(con, ico=None):
    """Ukaze, jak vypada skutecny zaznam z open dat RVZ a co z nej Extractor vytahl (bez stahovani)."""
    import glob
    import json as _json
    from ts import extractor
    from ts.sources import rvz
    from ts.util import CACHE_DIR
    one = lambda q: con.execute(q).fetchone()[0]
    out = {
        "databaze": {"zakazek": one("SELECT COUNT(*) FROM zakazky"), "vitezu": one("SELECT COUNT(*) FROM vitezove"),
                     "ucastniku": one("SELECT COUNT(*) FROM ucastnici"), "s_cpv": one("SELECT COUNT(*) FROM zakazky WHERE cpv != ''"),
                     "s_hodnotou": one("SELECT COUNT(*) FROM zakazky WHERE predpokladana_hodnota IS NOT NULL"),
                     "smluv": one("SELECT COUNT(*) FROM smlouvy")},
        "behy": [dict(r) for r in con.execute("SELECT krok, stav, poznamka FROM behy ORDER BY id DESC LIMIT 8")],
    }
    files = sorted(glob.glob(os.path.join(CACHE_DIR, "rvz_*.zip")), key=os.path.getmtime)
    out["stazene_soubory"] = [f"{os.path.basename(f)} ({os.path.getsize(f) >> 20} MB)" for f in files]
    out["kvalita"] = {
        "zakazky_bez_cpv": one("SELECT COUNT(*) FROM zakazky WHERE cpv IS NULL OR cpv = ''"),
        "vitezove_bez_ceny": one("SELECT COUNT(*) FROM vitezove WHERE cena_bez_dph IS NULL"),
        "vitezove_bez_ico": one("SELECT COUNT(*) FROM vitezove WHERE dodavatel_ico IS NULL"),
        "zakazky_s_2plus_ucastniky": one("SELECT COUNT(*) FROM (SELECT zakazka_id FROM ucastnici GROUP BY zakazka_id HAVING COUNT(*) >= 2)"),
    }
    if files:
        try:
            out["struktura"] = diagnostika_struktura(files, ico)
        except Exception as e:
            out["struktura_chyba"] = f"{type(e).__name__}: {e}"
    if files:
        try:
            recs = []
            for rec in rvz.iter_records(files[-1]):
                recs.append(rec)
                if len(recs) >= 3:
                    break
            out["soubor"] = os.path.basename(files[-1])
            if recs:
                out["klice_prvniho_zaznamu"] = extractor.describe_keys(recs[0], max_lines=250)
                out["extrahovano"] = [dict(zip(("zakazka", "vitezove", "ucastnici"), extractor.extract(r))) for r in recs]
                out["ukazka_zaznamu"] = _json.dumps(recs[0], ensure_ascii=False)[:6000]
        except Exception as e:
            out["chyba_cteni"] = f"{type(e).__name__}: {e}"
            try:
                import zipfile
                with zipfile.ZipFile(files[-1]) as z:
                    out["obsah_zipu"] = [f"{i.filename} ({i.file_size >> 10} kB)" for i in z.infolist()[:30]]
                    first = z.infolist()[0]
                    with z.open(first) as fh:
                        out["zacatek_souboru"] = fh.read(3000).decode("utf-8", "replace")
            except Exception as e2:
                out["chyba_zip"] = str(e2)
    return out


BEZP_HLAVICKY = {
    # OWASP HTTP Headers Cheat Sheet (prednaska, slajd 50)
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Permissions-Policy": "geolocation=(), camera=(), microphone=(), payment=()",
    "X-Frame-Options": "DENY",
    "Cross-Origin-Opener-Policy": "same-origin",
    "Cross-Origin-Resource-Policy": "same-origin",
    "Content-Security-Policy": ("default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
                                "img-src 'self' data:; connect-src 'self'; font-src 'self' data:; object-src 'none'; "
                                "base-uri 'self'; form-action 'self'; frame-ancestors 'none'"),
}


class Odmitnuto(Exception):
    def __init__(self, kod, zprava):
        super().__init__(zprava)
        self.kod, self.zprava = kod, zprava


def _ico_z_cesty(path):
    return bezpecnost.ico(unquote(path.rsplit("/", 1)[-1]))


class Handler(BaseHTTPRequestHandler):
    server_version = "TenderScope"
    sys_version = ""      # neprozrazovat verzi Pythonu
    timeout = 30          # pomale klienty (slowloris) odpojit

    def log_message(self, fmt, *args):
        pass

    # -------------------------------------------------------------- odpovedi
    def _hlavicky(self):
        for k, v in BEZP_HLAVICKY.items():
            self.send_header(k, v)
        if SEC["verejne"] and self.headers.get("X-Forwarded-Proto", "").lower() == "https":
            self.send_header("Strict-Transport-Security", "max-age=31536000; includeSubDomains")

    def _json(self, obj, code=200):
        body = json.dumps(obj, ensure_ascii=False, default=str).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self._hlavicky()
        self.end_headers()
        self.wfile.write(body)

    def _static(self, path):
        if not os.path.isdir(DIST):
            return self._json({"chyba": "Chybi web/dist - frontend neni sestaven."}, 500)
        rel = unquote(path).lstrip("/") or "index.html"
        full = os.path.realpath(os.path.join(DIST, rel))
        # path traversal: jen soubory uvnitr web/dist
        if os.path.commonpath([full, os.path.realpath(DIST)]) != os.path.realpath(DIST) or not os.path.isfile(full):
            full = os.path.join(DIST, "index.html")  # SPA
        ctype = mimetypes.guess_type(full)[0] or "application/octet-stream"
        if full.endswith(".js"):
            ctype = "text/javascript"
        with open(full, "rb") as f:
            data = f.read()
        self.send_response(200)
        self.send_header("Content-Type", ctype + ("; charset=utf-8" if ctype.startswith("text") else ""))
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "public, max-age=31536000, immutable" if "/assets/" in full else "no-cache")
        self._hlavicky()
        self.end_headers()
        self.wfile.write(data)

    def _chyba_serveru(self, e):
        """Uzivatel dostane obecnou hlasku s kodem, detail jde jen do logu (pravidlo 7)."""
        kod = secrets.token_hex(4)
        log("Server", f"chyba {kod}: {type(e).__name__}")
        traceback.print_exc()
        self._json({"chyba": f"Interní chyba serveru (kód {kod}). Podrobnosti jsou v logu."}, 500)

    # -------------------------------------------------------------- kontroly pred kazdym pozadavkem
    def _ip(self):
        xff = self.headers.get("X-Forwarded-For")
        if SEC["verejne"] and xff:
            casti = [c.strip() for c in xff.split(",") if c.strip()]
            if casti:  # posledni zaznam pridala nase proxy (Render), predchozi si klient muze vymyslet
                return casti[-min(SEC["proxy_hops"], len(casti))]
        return self.client_address[0]

    def _kontrola(self, metoda):
        host = (self.headers.get("Host") or "").lower()
        jmeno = host.rsplit(":", 1)[0].strip("[]") if host else ""
        if not SEC["verejne"]:
            # lokalni aplikace: jen localhost (ochrana proti DNS rebinding)
            if jmeno not in ("127.0.0.1", "localhost", "::1"):
                raise Odmitnuto(403, "Nepovolený Host.")
        elif SEC["hosty"] and jmeno not in SEC["hosty"]:
            raise Odmitnuto(403, "Nepovolený Host.")
        origin = self.headers.get("Origin")
        if origin and origin != "null":
            o = urlparse(origin)
            if (o.netloc or "").lower() != host:
                # cizi web nesmi volat nase API z prohlizece navstevnika (CORS/CSRF)
                raise Odmitnuto(403, "Požadavek z cizí stránky byl odmítnut.")
        elif origin == "null" and metoda == "POST":
            raise Odmitnuto(403, "Požadavek z cizí stránky byl odmítnut.")
        if not LIMIT_API.povol(self._ip()):
            raise Odmitnuto(429, "Příliš mnoho požadavků. Zkuste to za minutu.")

    def _telo(self):
        ctype = (self.headers.get("Content-Type") or "").split(";")[0].strip().lower()
        if ctype != "application/json":
            # jednoduchy formular z cizi stranky nemuze poslat application/json bez CORS povoleni
            raise Odmitnuto(415, "Očekávám JSON.")
        try:
            n = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            raise Odmitnuto(400, "Neplatná délka.")
        if n < 0 or n > MAX_TELO:
            raise Odmitnuto(413, "Požadavek je příliš velký.")
        try:
            body = json.loads(self.rfile.read(n) or b"{}")
        except (json.JSONDecodeError, UnicodeDecodeError):
            raise Odmitnuto(400, "Neplatný JSON.")
        if not isinstance(body, dict):
            raise Odmitnuto(400, "Neplatný JSON.")
        return body

    def _admin(self):
        """Pocitaji se jen CHYBNA hesla: po 5 chybach za 15 minut se z dane IP heslo vubec nezkousi."""
        ip = self._ip()
        zadal = SEC["verejne"] and bool(self.headers.get("X-Admin-Heslo"))
        if zadal and LIMIT_HESLO.vycerpano(ip):
            raise Odmitnuto(429, "Příliš mnoho pokusů o přihlášení. Zkuste to za 15 minut.")
        ok = je_admin(self.headers, ip)
        if zadal and not ok:
            LIMIT_HESLO.zapocitej(ip)
        return ok

    def _vyzaduj_admin(self):
        if not self._admin():
            log("Bezpecnost", f"odepren pristup k {urlparse(self.path).path} z {self._ip()}")
            raise Odmitnuto(403, NEPOVOLENO)

    def _vlastnik(self, admin):
        """Lokalne a pro spravce "" (spolecny prostor). Anonymni navstevnik online verze ma vlastni prostor."""
        if not SEC["verejne"] or admin:
            return ""
        return bezpecnost.vlastnik_z_hlavicky(self.headers.get("X-Uzivatel"))

    def _drahe(self):
        if not LIMIT_DRAHE.povol(self._ip()):
            raise Odmitnuto(429, "Příliš mnoho náročných požadavků. Zkuste to za minutu.")

    def _obsluz(self, metoda, fn):
        try:
            self._kontrola(metoda)
            fn()
        except Odmitnuto as e:
            self._json({"chyba": e.zprava}, e.kod)
        except bezpecnost.ChybaVstupu as e:
            self._json({"chyba": str(e)}, 400)
        except ValueError as e:  # nase hlasky z aplikacni logiky (napr. "Profil nenalezen")
            self._json({"chyba": str(e)[:200]}, 400)
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception as e:
            self._chyba_serveru(e)

    # -------------------------------------------------------------- GET
    def do_GET(self):
        self._obsluz("GET", self._get)

    def _get(self):
        u = urlparse(self.path)
        q = parse_qs(u.query)
        arg = lambda k, n: bezpecnost.text((q.get(k) or [""])[0], n, k)
        if not u.path.startswith("/api/"):
            return self._static(u.path)
        con = connect(STATE["db"])
        try:
            if u.path == "/api/stav":
                return self._json({**api.stav(con, STATE["demo"]), "aktualizace_bezi": JOB["bezi"]})
            if u.path == "/api/hledat":
                return self._json(api.hledat(con, arg("q", 100), None if STATE["demo"] else STATE["cfg"]["zdroje"]["ares_base"]))
            if u.path.startswith("/api/firma/"):
                return self._json(api.profil(con, _ico_z_cesty(u.path), STATE["cfg"], online=not STATE["demo"]))
            if u.path == "/api/trh":
                return self._json(api.trh(con, arg("segment", 40) or None))
            if u.path == "/api/nastaveni":
                return self._json(nastaveni_get(self._admin()))
            if u.path.startswith("/api/export-zip/"):
                ico = _ico_z_cesty(u.path)
                if ico not in EXPORTS:
                    return self._json({"chyba": "Export nejdřív vytvořte."}, 404)
                name, data = EXPORTS[ico]
                self.send_response(200)
                self.send_header("Content-Type", "application/zip")
                self.send_header("Content-Disposition", f'attachment; filename="{name}"')
                self.send_header("Content-Length", str(len(data)))
                self._hlavicky()
                self.end_headers()
                self.wfile.write(data)
                return
            if u.path == "/api/onboarding":
                return self._json(onboarding.seznam(con, self._vlastnik(self._admin())))
            if u.path.startswith("/api/onboarding/"):
                st = onboarding.nacti(con, _ico_z_cesty(u.path), self._vlastnik(self._admin()))
                if not st:
                    return self._json({"chyba": "Profil nenalezen"}, 404)
                if st.get("profil"):
                    st["zpravodaj"] = onboarding.zpravodaj(con, st["profil"])
                return self._json(st)
            if u.path.startswith("/api/vhodnost/"):
                return self._json(onboarding.vhodnost_jedne(con, _ico_z_cesty(u.path), arg("zakazka", 200),
                                                            vlastnik=self._vlastnik(self._admin())))
            if u.path == "/api/diagnostika":
                self._vyzaduj_admin()
                ico = arg("ico", 12)
                return self._json(diagnostika(con, bezpecnost.ico(ico) if ico else None))
            if u.path == "/api/beh":
                return self._json({k: JOB[k] for k in ("bezi", "rezim", "chyba", "zacatek", "konec")} | {"log": JOB["log"][-150:]})
        finally:
            con.close()
        self._json({"chyba": "neznámý endpoint"}, 404)

    # -------------------------------------------------------------- POST
    def do_POST(self):
        self._obsluz("POST", self._post)

    def _post(self):
        u = urlparse(self.path)
        body = self._telo()
        admin = self._admin()
        if u.path == "/api/nastaveni":
            self._vyzaduj_admin()
            return self._json(nastaveni_set(body) | {"admin": True})
        if u.path in ("/api/ai/modely", "/api/ai/test"):
            self._vyzaduj_admin()
            self._drahe()
            return self._json(ai_akce(body, "modely" if u.path.endswith("modely") else "test"))
        if u.path == "/api/aktualizovat":
            self._vyzaduj_admin()
            rezim = body.get("rezim", "rychle")
            if rezim not in ("rychle", "plny"):
                raise bezpecnost.ChybaVstupu("Neznámý režim aktualizace.")
            if not spust_aktualizaci(rezim):
                return self._json({"ok": False, "zprava": "Aktualizace už běží."}, 409)
            log("Bezpecnost", f"aktualizace dat ({rezim}) spustena z {self._ip()}")
            return self._json({"ok": True})
        if u.path.startswith("/api/export/"):
            self._drahe()
            ico = _ico_z_cesty(u.path)
            # na serveru se do slozky trezoru nezapisuje, jen se nabidne zip ke stazeni
            return self._json(export_obsidian(ico, bool(body.get("zapsat", True)) and not SEC["verejne"], cfg_pro(admin)))
        if u.path.startswith("/api/onboarding/"):
            vlastnik = self._vlastnik(admin)
            con = connect(STATE["db"])
            try:
                if u.path == "/api/onboarding/start":
                    self._drahe()
                    ico = bezpecnost.ico(body.get("ico"))
                    web = bezpecnost.over_url(body.get("web")) if (body.get("web") and not STATE["demo"]) else None
                    return self._json(onboarding.start(con, cfg_pro(admin), ico, web, online=not STATE["demo"],
                                                       vlastnik=vlastnik, llm_povolit=LLM_DEN.vezmi))
                if u.path == "/api/onboarding/dokoncit":
                    self._drahe()
                    return self._json(onboarding.dokonci(con, cfg_pro(admin), bezpecnost.ico(body.get("ico")),
                                                         bezpecnost.odpovedi(body.get("odpovedi") or {}),
                                                         vlastnik=vlastnik, llm_povolit=LLM_DEN.vezmi))
                if u.path.endswith("/profil"):
                    profil = body.get("profil")
                    if not isinstance(profil, dict):
                        raise bezpecnost.ChybaVstupu("Neplatný profil.")
                    ico = bezpecnost.ico(unquote(u.path.split("/")[3]))
                    return self._json(onboarding.uloz_profil(con, ico, profil, vlastnik=vlastnik))
            finally:
                con.close()
        self._json({"chyba": "neznámý endpoint"}, 404)

    def do_PUT(self):
        self._obsluz("PUT", lambda: self._json({"chyba": "metoda není povolena"}, 405))

    do_DELETE = do_PATCH = do_PUT

    def do_OPTIONS(self):
        # zadne CORS: API smi volat jen nase vlastni stranka (same-origin)
        self._obsluz("OPTIONS", lambda: self._json({"chyba": "CORS není povolen"}, 405))


def spust_aktualizaci(rezim):
    with JOB_LOCK:
        if JOB["bezi"]:
            return False
        JOB.update({"bezi": True, "rezim": rezim, "log": [], "chyba": None,
                    "zacatek": datetime.now().isoformat(timespec="seconds"), "konec": None})
    threading.Thread(target=run_update, args=(rezim,), daemon=True).start()
    return True


def stahni_databazi(url, cil, max_bajtu=500_000_000):
    """Stahne zabalenou databazi (tenderscope.db.gz) z adresy v TS_DB_URL. Jen https na verejny server (SSRF),
    velikost omezena, a pred pouzitim se overi, ze jde opravdu o databazi TenderScope. Pri chybe se nic nezmeni."""
    import gzip
    import sqlite3
    import requests
    tmp_gz, tmp_db = cil + ".dl.gz", cil + ".dl"
    try:
        url = bezpecnost.over_api_url(url, True)
        print("Stahuji aktualni databazi z TS_DB_URL ...")
        with requests.get(url, stream=True, timeout=60, allow_redirects=False) as r:
            if r.status_code != 200:
                raise RuntimeError(f"HTTP {r.status_code}")
            got = 0
            with open(tmp_gz, "wb") as f:
                for chunk in r.iter_content(1 << 20):
                    got += len(chunk)
                    if got > max_bajtu:
                        raise RuntimeError("soubor je prilis velky")
                    f.write(chunk)
        got = 0
        with gzip.open(tmp_gz, "rb") as g, open(tmp_db, "wb") as f:
            while True:
                blok = g.read(1 << 20)
                if not blok:
                    break
                got += len(blok)
                if got > 4 * max_bajtu:
                    raise RuntimeError("rozbalena databaze je prilis velka")
                f.write(blok)
        con = sqlite3.connect(tmp_db)
        n = con.execute("SELECT COUNT(*) FROM zakazky").fetchone()[0]
        con.close()
        os.replace(tmp_db, cil)
        print(f"Databaze stazena ({n} zakazek).")
        return True
    except Exception as e:  # zadna databaze ke stazeni (napr. vetev data jeste neexistuje) -> pokracujeme bez ni
        print(f"Databazi z TS_DB_URL se nepodarilo pouzit: {str(e)[:200]}")
        return False
    finally:
        for t in (tmp_gz, tmp_db):
            if os.path.exists(t):
                os.remove(t)


def main():
    env = os.environ.get
    p = argparse.ArgumentParser()
    p.add_argument("--demo", action="store_true", default=env("TS_DEMO") == "1", help="umela data bez internetu")
    p.add_argument("--port", type=int, default=int(env("PORT") or 8765))
    p.add_argument("--host", default=env("TS_HOST") or "127.0.0.1", help="0.0.0.0 = prijimat spojeni zvenku (server)")
    p.add_argument("--neotvirat", action="store_true")
    p.add_argument("--auto-aktualizace", default=env("TS_AUTO_AKTUALIZACE") or "",
                   help="'rychle' nebo 'plny': pri prazdne databazi hned po startu stahne data (pro server)")
    a = p.parse_args()
    if a.host not in ("127.0.0.1", "localhost", "::1") and not SEC["verejne"]:
        # fail closed: server dostupny zvenku je vzdy v rezimu online verze (zapisy jen s heslem)
        SEC["verejne"] = True
    STATE["cfg"] = load_config()
    if a.demo:
        STATE["demo"] = True
        STATE["db"] = os.path.join(DATA_DIR, "demo_app.db")
        if not os.path.exists(STATE["db"]):
            print("Pripravuji demo data (jednou, par sekund)...")
            import demo
            demo.build_demo_db(STATE["db"])
    db_url = env("TS_DB_URL")  # aktualni databaze z vetve "data" na GitHubu (plni ji aktualizovat_online.bat / GitHub Actions)
    if not a.demo and not os.path.exists(STATE["db"]) and db_url:
        stahni_databazi(db_url, STATE["db"])
    pripravena = os.path.join(ROOT, "predpripravena_db", "tenderscope.db.gz")
    if not a.demo and not os.path.exists(STATE["db"]) and os.path.exists(pripravena):
        # server: zabalena databaze nahrana spolu s aplikaci (pripravit_db.py) -> rozbalime do data/
        import gzip
        import shutil
        print("Rozbaluji predpripravenou databazi z predpripravena_db/ ...")
        with gzip.open(pripravena, "rb") as g, open(STATE["db"] + ".tmp", "wb") as f:
            shutil.copyfileobj(g, f)
        os.replace(STATE["db"] + ".tmp", STATE["db"])
    con = connect(STATE["db"])
    if con.execute("SELECT COUNT(*) FROM dodavatele").fetchone()[0] == 0 and con.execute("SELECT COUNT(*) FROM vitezove").fetchone()[0] > 0:
        api.rebuild_index(con)  # databaze z prikazove radky -> doplnime index
    prazdna = con.execute("SELECT COUNT(*) FROM zakazky").fetchone()[0] == 0
    con.close()
    if a.auto_aktualizace in ("rychle", "plny") and prazdna and not a.demo:
        print(f"Databaze je prazdna -> spoustim automatickou aktualizaci ({a.auto_aktualizace})")
        spust_aktualizaci(a.auto_aktualizace)
    srv = ThreadingHTTPServer((a.host, a.port), Handler)
    url = f"http://127.0.0.1:{a.port}/"
    if SEC["verejne"]:
        print("  Online verze: zapisy jen s admin heslem" + ("" if SEC["heslo"] else " (TS_ADMIN_HESLO neni nastaveno -> jen prohlizeni)"))
        if SEC["heslo"] and len(SEC["heslo"]) < 12:
            print("  VAROVANI: admin heslo je kratke, pouzijte aspon 12 znaku.")
    print(f"\n  TenderScope bezi na {url}  ({'DEMO data' if a.demo else 'realna data'})")
    print("  Aplikaci ukoncite zavrenim tohoto okna nebo Ctrl+C.\n")
    if not a.neotvirat:
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
