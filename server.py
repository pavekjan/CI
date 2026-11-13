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
import json
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

from ts import api, onboarding, scout, verifier  # noqa: E402
from ts.db import connect  # noqa: E402
from ts.util import DATA_DIR, LOG_SINKS, load_config, log  # noqa: E402

DIST = os.path.join(ROOT, "web", "dist")
STATE = {"demo": False, "db": os.path.join(DATA_DIR, "tenderscope.db"), "cfg": None}
JOB = {"bezi": False, "rezim": None, "log": [], "chyba": None, "zacatek": None, "konec": None}
JOB_LOCK = threading.Lock()
EXPORTS = {}  # ico -> (nazev souboru, bytes zipu)
CONFIG_PATH = os.path.join(ROOT, "config.json")


def nastaveni_get():
    c = STATE["cfg"]
    key = c.get("exa_api_key") or ""
    ak = c.get("anthropic_api_key") or ""
    from ts import llm
    return {"obsidian_vault": c.get("obsidian_vault") or "", "exa_api_key_nastaven": bool(key),
            "exa_api_key_nahled": (key[:4] + "…" + key[-3:]) if len(key) > 8 else "",
            "anthropic_api_key_nastaven": bool(ak), "anthropic_api_key_nahled": (ak[:7] + "…" + ak[-4:]) if len(ak) > 12 else "",
            "anthropic_model": c.get("anthropic_model") or llm.DEFAULT_MODEL, "anthropic_sdk": llm.dostupne()}


def nastaveni_set(body):
    with open(CONFIG_PATH, encoding="utf-8") as f:
        raw = json.load(f)
    for k in ("obsidian_vault", "exa_api_key", "anthropic_api_key", "anthropic_model"):
        if k in body and body[k] is not None:
            raw[k] = str(body[k]).strip()
            STATE["cfg"][k] = raw[k]
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(raw, f, ensure_ascii=False, indent=2)
    return nastaveni_get()


def export_obsidian(ico, zapsat):
    from ts import obsidian
    con = connect(STATE["db"])
    try:
        online = not STATE["demo"]
        p = api.profil(con, ico, STATE["cfg"], online=online)
        exa = []
        key = STATE["cfg"].get("exa_api_key")
        if key and online and p["nazev"] != p["ico"]:
            exa = obsidian.exa_search(key, f'"{p["nazev"]}" veřejné zakázky', 6) + obsidian.exa_search(key, f'{p["nazev"]} firma novinky', 4)
        v = obsidian.export_firma(con, p, STATE["cfg"], exa)
    finally:
        con.close()
    name = f"TenderScope_{obsidian.safe(p['nazev'], 40).replace(' ', '_')}.zip"
    EXPORTS[ico] = (name, v.zip_bytes())
    out = {"ok": True, "nazev": p["nazev"], "poznamek": len(v.files), "zdroju": v.n_src, "exa": len(exa),
           "zip": f"/api/export-zip/{ico}", "zapsano": None}
    vault = STATE["cfg"].get("obsidian_vault")
    if zapsat and vault:
        if not os.path.isdir(vault):
            out["chyba_zapisu"] = f"Složka trezoru neexistuje: {vault}"
        else:
            v.write_dir(vault)
            out["zapsano"] = os.path.join(vault, obsidian.ROOT_DIR)
    return out


def _sink(line):
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


class Handler(BaseHTTPRequestHandler):
    server_version = "TenderScope/1.0"

    def log_message(self, fmt, *args):
        pass

    def _json(self, obj, code=200):
        body = json.dumps(obj, ensure_ascii=False, default=str).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _static(self, path):
        if not os.path.isdir(DIST):
            return self._json({"chyba": "Chybi web/dist - frontend neni sestaven."}, 500)
        rel = path.lstrip("/") or "index.html"
        full = os.path.normpath(os.path.join(DIST, rel))
        if not full.startswith(DIST) or not os.path.isfile(full):
            full = os.path.join(DIST, "index.html")  # SPA
        ctype = mimetypes.guess_type(full)[0] or "application/octet-stream"
        if full.endswith(".js"):
            ctype = "text/javascript"
        with open(full, "rb") as f:
            data = f.read()
        self.send_response(200)
        self.send_header("Content-Type", ctype + ("; charset=utf-8" if ctype.startswith("text") else ""))
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        u = urlparse(self.path)
        q = parse_qs(u.query)
        try:
            if not u.path.startswith("/api/"):
                return self._static(u.path)
            con = connect(STATE["db"])
            try:
                if u.path == "/api/stav":
                    return self._json({**api.stav(con, STATE["demo"]), "aktualizace_bezi": JOB["bezi"]})
                if u.path == "/api/hledat":
                    return self._json(api.hledat(con, q.get("q", [""])[0],
                                                 None if STATE["demo"] else STATE["cfg"]["zdroje"]["ares_base"]))
                if u.path.startswith("/api/firma/"):
                    ico = unquote(u.path.rsplit("/", 1)[-1])
                    return self._json(api.profil(con, ico, STATE["cfg"], online=not STATE["demo"]))
                if u.path == "/api/trh":
                    return self._json(api.trh(con, q.get("segment", [None])[0] or None))
                if u.path == "/api/nastaveni":
                    return self._json(nastaveni_get())
                if u.path.startswith("/api/export-zip/"):
                    ico = unquote(u.path.rsplit("/", 1)[-1])
                    if ico not in EXPORTS:
                        return self._json({"chyba": "Export nejdřív vytvořte."}, 404)
                    name, data = EXPORTS[ico]
                    self.send_response(200)
                    self.send_header("Content-Type", "application/zip")
                    self.send_header("Content-Disposition", f'attachment; filename="{name}"')
                    self.send_header("Content-Length", str(len(data)))
                    self.end_headers()
                    self.wfile.write(data)
                    return
                if u.path == "/api/onboarding":
                    return self._json(onboarding.seznam(con))
                if u.path.startswith("/api/onboarding/"):
                    st = onboarding.nacti(con, unquote(u.path.rsplit("/", 1)[-1]))
                    if not st:
                        return self._json({"chyba": "Profil nenalezen"}, 404)
                    if st.get("profil"):
                        st["zpravodaj"] = onboarding.zpravodaj(con, st["profil"])
                    return self._json(st)
                if u.path.startswith("/api/vhodnost/"):
                    return self._json(onboarding.vhodnost_jedne(con, unquote(u.path.rsplit("/", 1)[-1]), q.get("zakazka", [""])[0]))
                if u.path == "/api/diagnostika":
                    return self._json(diagnostika(con, q.get("ico", [None])[0]))
                if u.path == "/api/beh":
                    return self._json({k: JOB[k] for k in ("bezi", "rezim", "chyba", "zacatek", "konec")} | {"log": JOB["log"][-150:]})
            finally:
                con.close()
            self._json({"chyba": "neznamy endpoint"}, 404)
        except ValueError as e:
            self._json({"chyba": str(e)}, 400)
        except Exception as e:
            traceback.print_exc()
            self._json({"chyba": str(e)}, 500)

    def do_POST(self):
        u = urlparse(self.path)
        n = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(n) or b"{}")
        try:
            if u.path == "/api/nastaveni":
                return self._json(nastaveni_set(body))
            if u.path.startswith("/api/onboarding/"):
                con = connect(STATE["db"])
                try:
                    if u.path == "/api/onboarding/start":
                        return self._json(onboarding.start(con, STATE["cfg"], body.get("ico", ""), body.get("web") or None,
                                                           online=not STATE["demo"]))
                    if u.path == "/api/onboarding/dokoncit":
                        return self._json(onboarding.dokonci(con, STATE["cfg"], body.get("ico", ""), body.get("odpovedi") or {}))
                    if u.path.endswith("/profil"):
                        return self._json(onboarding.uloz_profil(con, unquote(u.path.split("/")[3]), body.get("profil") or {}))
                finally:
                    con.close()
            if u.path.startswith("/api/export/"):
                return self._json(export_obsidian(unquote(u.path.rsplit("/", 1)[-1]), bool(body.get("zapsat", True))))
        except ValueError as e:
            return self._json({"chyba": str(e)}, 400)
        except Exception as e:
            traceback.print_exc()
            return self._json({"chyba": str(e)}, 500)
        if u.path != "/api/aktualizovat":
            return self._json({"chyba": "neznamy endpoint"}, 404)
        rezim = body.get("rezim", "rychle")
        with JOB_LOCK:
            if JOB["bezi"]:
                return self._json({"ok": False, "zprava": "Aktualizace uz bezi."}, 409)
            JOB.update({"bezi": True, "rezim": rezim, "log": [], "chyba": None,
                        "zacatek": datetime.now().isoformat(timespec="seconds"), "konec": None})
        threading.Thread(target=run_update, args=(rezim,), daemon=True).start()
        self._json({"ok": True})


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--demo", action="store_true", help="umela data bez internetu")
    p.add_argument("--port", type=int, default=8765)
    p.add_argument("--neotvirat", action="store_true")
    a = p.parse_args()
    STATE["cfg"] = load_config()
    if a.demo:
        STATE["demo"] = True
        STATE["db"] = os.path.join(DATA_DIR, "demo_app.db")
        if not os.path.exists(STATE["db"]):
            print("Pripravuji demo data (jednou, par sekund)...")
            import demo
            demo.build_demo_db(STATE["db"])
    con = connect(STATE["db"])
    if con.execute("SELECT COUNT(*) FROM dodavatele").fetchone()[0] == 0 and con.execute("SELECT COUNT(*) FROM vitezove").fetchone()[0] > 0:
        api.rebuild_index(con)  # databaze z prikazove radky -> doplnime index
    con.close()
    srv = ThreadingHTTPServer(("127.0.0.1", a.port), Handler)
    url = f"http://127.0.0.1:{a.port}/"
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
