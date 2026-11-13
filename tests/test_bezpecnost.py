"""Bezpecnostni testy TenderScope (prednaska "Bezpecny vibe coding", slajd 60).

Spusteni:  python -m unittest discover -s tests -v
Bezi i v GitHub Actions pred kazdym mergem. Testy NEUPRAVUJTE ani neoslabujte, aby prosly.

Overuje:
- nepřihlášený nemá přístup k admin akcím (403), špatné heslo neprojde, chybějící heslo = zamítnuto (fail closed)
- test dvou uživatelů: B nevidí ani nezmění onboarding uživatele A
- SQL injection vstupy nic nevyzradí a server nespadne
- validace vstupů, limity velikosti, Content-Type, cizí Origin (CSRF/CORS), Host (DNS rebinding)
- path traversal, bezpečnostní hlavičky, rate limiting, ochrana proti SSRF, CSV injection
- v repozitáři nejsou tajemství
"""
import json
import os
import socket
import subprocess
import sys
import time
import unittest
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from ts import bezpecnost  # noqa: E402

HESLO = "testovaci-heslo-pro-ci-123"


def volny_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def spust_server(env_navic):
    port = volny_port()
    env = {k: v for k, v in os.environ.items() if not k.startswith("TS_") and k not in ("ANTHROPIC_API_KEY", "EXA_API_KEY")}
    env.update({"TS_DEMO": "1", "PYTHONUNBUFFERED": "1"}, **env_navic)
    p = subprocess.Popen([sys.executable, os.path.join(ROOT, "server.py"), "--neotvirat", "--port", str(port)],
                         cwd=ROOT, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    url = f"http://127.0.0.1:{port}"
    for _ in range(120):
        try:
            urllib.request.urlopen(url + "/api/stav", timeout=2)
            return p, url
        except Exception:
            if p.poll() is not None:
                raise RuntimeError(p.stdout.read().decode(errors="replace"))
            time.sleep(0.5)
    p.kill()
    raise RuntimeError("server nenastartoval")


def zavolej(url, cesta, metoda="GET", telo=None, hlavicky=None, ctype="application/json"):
    data = None
    h = dict(hlavicky or {})
    if telo is not None:
        data = telo if isinstance(telo, bytes) else json.dumps(telo).encode()
        h.setdefault("Content-Type", ctype)
    req = urllib.request.Request(url + cesta, data=data, method=metoda, headers=h)
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            raw = r.read()
            return r.status, raw, dict(r.headers)
    except urllib.error.HTTPError as e:
        return e.code, e.read(), dict(e.headers)


def jj(raw):
    try:
        return json.loads(raw)
    except Exception:
        return None


class OnlineVerze(unittest.TestCase):
    """Server v rezimu online verze (jako na Renderu) s admin heslem."""

    @classmethod
    def setUpClass(cls):
        cls.proc, cls.url = spust_server({"TS_VEREJNE": "1", "TS_ADMIN_HESLO": HESLO,
                                          "TS_LIMIT_ZA_MINUTU": "1000", "TS_LIMIT_DRAHE_ZA_MINUTU": "1000"})
        import demo
        cls.ico = demo.FIRMY[0][0]

    @classmethod
    def tearDownClass(cls):
        cls.proc.kill()
        cls.proc.wait()
        cls.proc.stdout.close()

    def u(self, uid):
        return {"X-Uzivatel": uid}

    # ---------------------------------------------------------- nepřihlášený a admin akce
    def test_neprihlaseny_nesmi_admin_akce(self):
        for metoda, cesta, telo in [("POST", "/api/nastaveni", {"anthropic_api_key": "sk-ant-x"}),
                                    ("POST", "/api/aktualizovat", {"rezim": "rychle"}),
                                    ("GET", "/api/diagnostika", None)]:
            kod, raw, _ = zavolej(self.url, cesta, metoda, telo)
            self.assertEqual(kod, 403, f"{metoda} {cesta} musí být zamítnuto, vrátilo {kod}")

    def test_spatne_heslo_neprojde(self):
        kod, _, _ = zavolej(self.url, "/api/nastaveni", "POST", {"obsidian_vault": "x"}, {"X-Admin-Heslo": "spatne"})
        self.assertIn(kod, (403, 429))
        kod, raw, _ = zavolej(self.url, "/api/nastaveni", hlavicky={"X-Admin-Heslo": "spatne"})
        self.assertIn(kod, (200, 429))
        if kod == 200:
            self.assertFalse(jj(raw)["admin"])

    def test_spravne_heslo_projde(self):
        kod, raw, _ = zavolej(self.url, "/api/nastaveni", hlavicky={"X-Admin-Heslo": HESLO})
        self.assertEqual(kod, 200)
        self.assertTrue(jj(raw)["admin"])

    def test_navstevnik_nevidi_klice_ani_cesty(self):
        kod, raw, _ = zavolej(self.url, "/api/nastaveni")
        d = jj(raw)
        # zadny nahled klice ani adresa API zadneho poskytovatele AI, zadna cesta na disku
        for p in d["ai"]["poskytovatele"]:
            self.assertEqual(p["klic_nahled"], "", p["id"])
            self.assertEqual(p["url"], "", p["id"])
        self.assertEqual(d["exa_api_key_nahled"], "")
        self.assertEqual(d["obsidian_vault"], "")

    # ---------------------------------------------------------- test dvou uživatelů (BOLA / IDOR)
    def test_uzivatel_b_nevidi_onboarding_uzivatele_a(self):
        a, b = self.u("a" * 32), self.u("b" * 32)
        kod, raw, _ = zavolej(self.url, "/api/onboarding/start", "POST", {"ico": self.ico, "web": ""}, a)
        self.assertEqual(kod, 200, raw)
        # A svuj profil vidi
        kod, _, _ = zavolej(self.url, f"/api/onboarding/{self.ico}", hlavicky=a)
        self.assertEqual(kod, 200)
        # B ho nevidi ani v seznamu, ani primo - dostane "nenalezeno", ne "zakazano"
        kod, _, _ = zavolej(self.url, f"/api/onboarding/{self.ico}", hlavicky=b)
        self.assertEqual(kod, 404)
        kod, raw, _ = zavolej(self.url, "/api/onboarding", hlavicky=b)
        self.assertNotIn(self.ico, [x["ico"] for x in jj(raw)])
        # B ho nezmeni ani nedokonci
        kod, _, _ = zavolej(self.url, f"/api/onboarding/{self.ico}/profil", "POST", {"profil": {"nazev": "hack"}}, b)
        self.assertEqual(kod, 400)
        kod, _, _ = zavolej(self.url, "/api/onboarding/dokoncit", "POST", {"ico": self.ico, "odpovedi": {}}, b)
        self.assertEqual(kod, 400)
        # bez prihlaseni / bez ID prohlizece taky nic
        kod, _, _ = zavolej(self.url, f"/api/onboarding/{self.ico}")
        self.assertEqual(kod, 400)

    # ---------------------------------------------------------- SQL injection
    def test_sql_injection(self):
        kod, raw, _ = zavolej(self.url, "/api/hledat?q=" + urllib.request.quote("' OR '1'='1"))
        self.assertEqual(kod, 200)
        kod_vse, raw_vse, _ = zavolej(self.url, "/api/hledat?q=a")
        self.assertLessEqual(len(jj(raw)), len(jj(raw_vse)))
        self.assertEqual(jj(raw), [], "injection nesmí vrátit všechny firmy")
        for cesta in ["/api/firma/" + urllib.request.quote("1' OR '1'='1"),
                      "/api/firma/" + urllib.request.quote("1; DROP TABLE zakazky;--"),
                      f"/api/vhodnost/{self.ico}?zakazka=" + urllib.request.quote("x' OR 1=1--")]:
            kod, raw, _ = zavolej(self.url, cesta, hlavicky=self.u("c" * 32))
            self.assertIn(kod, (400, 404), cesta)
        kod, raw, _ = zavolej(self.url, "/api/trh?segment=" + urllib.request.quote("45' OR 1=1 --"))
        self.assertEqual(kod, 200)
        kod, raw, _ = zavolej(self.url, "/api/stav")
        self.assertGreater(jj(raw)["zakazek"], 0, "tabulka zakázek musí přežít")

    # ---------------------------------------------------------- vstupy a limity
    def test_validace_vstupu(self):
        kod, raw, _ = zavolej(self.url, "/api/onboarding/start", "POST", {"ico": "abc"}, self.u("d" * 32))
        self.assertEqual(kod, 400)
        kod, _, _ = zavolej(self.url, "/api/hledat?q=" + "x" * 500)
        self.assertEqual(kod, 400)
        kod, _, _ = zavolej(self.url, "/api/onboarding/start", "POST", b"{nejson", self.u("d" * 32))
        self.assertEqual(kod, 400)
        kod, _, _ = zavolej(self.url, "/api/onboarding/start", "POST", b"x" * (600 * 1024), self.u("d" * 32))
        self.assertEqual(kod, 413)

    def test_post_bez_json_a_z_cizi_stranky(self):
        kod, _, _ = zavolej(self.url, "/api/aktualizovat", "POST", b"rezim=plny", {"X-Admin-Heslo": HESLO},
                            ctype="application/x-www-form-urlencoded")
        self.assertEqual(kod, 415)
        kod, _, _ = zavolej(self.url, "/api/onboarding/start", "POST", {"ico": self.ico},
                            {"Origin": "https://zla-stranka.example", **self.u("e" * 32)})
        self.assertEqual(kod, 403)

    def test_zadny_cors(self):
        kod, _, h = zavolej(self.url, "/api/stav", hlavicky={"Origin": "https://zla-stranka.example"})
        self.assertEqual(kod, 403)
        self.assertNotIn("Access-Control-Allow-Origin", h)
        kod, _, _ = zavolej(self.url, "/api/stav", "OPTIONS")
        self.assertEqual(kod, 405)

    def test_path_traversal(self):
        for cesta in ["/../config.json", "/%2e%2e/config.json", "/..%2fserver.py", "/assets/../../server.py"]:
            kod, raw, _ = zavolej(self.url, cesta)
            self.assertNotIn(b"anthropic_api_key", raw)
            self.assertNotIn(b"import ", raw)

    def test_bezpecnostni_hlavicky(self):
        for cesta in ["/", "/api/stav"]:
            _, _, h = zavolej(self.url, cesta)
            self.assertEqual(h.get("X-Content-Type-Options"), "nosniff")
            self.assertIn("frame-ancestors 'none'", h.get("Content-Security-Policy", ""))
            self.assertEqual(h.get("X-Frame-Options"), "DENY")
            self.assertIn("Referrer-Policy", h)
            self.assertNotIn("Python", h.get("Server", ""))

    def test_chyba_neprozradi_detail(self):
        kod, raw, _ = zavolej(self.url, "/api/neexistuje")
        self.assertEqual(kod, 404)
        self.assertNotIn(b"Traceback", raw)


class BruteForce(unittest.TestCase):
    def test_hadani_hesla_se_zablokuje(self):
        p, url = spust_server({"TS_VEREJNE": "1", "TS_ADMIN_HESLO": HESLO})
        try:
            kody = [zavolej(url, "/api/nastaveni", "POST", {}, {"X-Admin-Heslo": f"zkouska{i}"})[0] for i in range(7)]
            self.assertEqual(kody[-1], 429, kody)
            # ani spravne heslo uz z te IP chvili neprojde
            self.assertEqual(zavolej(url, "/api/nastaveni", "POST", {}, {"X-Admin-Heslo": HESLO})[0], 429)
        finally:
            p.kill(); p.wait(); p.stdout.close()

    def test_rate_limit(self):
        p, url = spust_server({"TS_VEREJNE": "1", "TS_LIMIT_ZA_MINUTU": "5"})
        try:
            kody = [zavolej(url, "/api/stav")[0] for _ in range(8)]
            self.assertIn(429, kody)
        finally:
            p.kill(); p.wait(); p.stdout.close()


class FailClosed(unittest.TestCase):
    def test_online_bez_hesla_nikdo_nema_admin(self):
        """Kdyz spravce zapomene nastavit TS_ADMIN_HESLO, admin akce nesmi projit nikomu."""
        p, url = spust_server({"TS_VEREJNE": "1"})
        try:
            self.assertEqual(zavolej(url, "/api/aktualizovat", "POST", {"rezim": "rychle"}, {"X-Admin-Heslo": ""})[0], 403)
            self.assertEqual(zavolej(url, "/api/aktualizovat", "POST", {"rezim": "rychle"}, {"X-Admin-Heslo": "cokoli"})[0], 403)
        finally:
            p.kill(); p.wait(); p.stdout.close()

    def test_vyjimka_pri_kontrole_zamitne(self):
        import server

        class Rozbite:
            def get(self, *a):
                raise RuntimeError("rozbito")
        stare = dict(server.SEC)
        try:
            server.SEC.update({"verejne": True, "heslo": "x"})
            self.assertFalse(server.je_admin(Rozbite()))
        finally:
            server.SEC.clear(); server.SEC.update(stare)

    def test_lokalni_server_odmitne_cizi_host(self):
        """DNS rebinding: lokalni aplikace odpovida jen na 127.0.0.1 / localhost."""
        p, url = spust_server({})
        try:
            self.assertEqual(zavolej(url, "/api/stav", hlavicky={"Host": "zla-stranka.example"})[0], 403)
            self.assertEqual(zavolej(url, "/api/stav")[0], 200)
        finally:
            p.kill(); p.wait(); p.stdout.close()


class Jednotky(unittest.TestCase):
    def test_ssrf_vnitrni_adresy_odmitnuty(self):
        for url in ["http://127.0.0.1", "http://localhost:8765/api/nastaveni", "http://169.254.169.254/latest/meta-data/",
                    "http://10.0.0.1", "http://192.168.1.1", "http://[::1]/", "http://0.0.0.0", "file:///etc/passwd",
                    "ftp://example.com", "http://user:heslo@example.com", "http://example.com:6379"]:
            with self.assertRaises(bezpecnost.ChybaVstupu, msg=url):
                bezpecnost.over_url(url)

    def test_ico(self):
        self.assertEqual(bezpecnost.ico("177041"), "00177041")
        for spatne in ["", "abc", "123456789", "1' OR '1'='1", None]:
            with self.assertRaises(bezpecnost.ChybaVstupu):
                bezpecnost.ico(spatne)

    def test_csv_injection(self):
        self.assertEqual(bezpecnost.bunka_csv("=HYPERLINK(\"http://zlo\")"), "'=HYPERLINK(\"http://zlo\")")
        self.assertEqual(bezpecnost.bunka_csv("@SUM(A1)"), "'@SUM(A1)")
        self.assertEqual(bezpecnost.bunka_csv("Stavby s.r.o."), "Stavby s.r.o.")

    def test_denni_limit_utrat(self):
        lim = bezpecnost.DenniLimit(3)
        self.assertEqual([lim.vezmi() for _ in range(5)], [True, True, True, False, False])
        self.assertFalse(bezpecnost.DenniLimit(0).vezmi())

    def test_klic_api_a_model(self):
        with self.assertRaises(bezpecnost.ChybaVstupu):
            bezpecnost.klic_api("sk-ant-<script>", "klic")
        with self.assertRaises(bezpecnost.ChybaVstupu):
            bezpecnost.model("gpt-4; rm -rf /")


class Tajemstvi(unittest.TestCase):
    def test_config_v_repozitari_nema_klice(self):
        with open(os.path.join(ROOT, "config.json"), encoding="utf-8") as f:
            cfg = json.load(f)
        for k in ("anthropic_api_key", "exa_api_key", "hlidac_token"):
            self.assertEqual(cfg.get(k, ""), "", f"{k} v config.json musí být prázdný")

    def test_env_example_bez_hodnot(self):
        with open(os.path.join(ROOT, ".env.example"), encoding="utf-8") as f:
            for radek in f:
                radek = radek.strip()
                if radek and not radek.startswith("#") and "=" in radek:
                    k, v = radek.split("=", 1)
                    if k.endswith(("KEY", "TOKEN", "HESLO")):
                        self.assertEqual(v.strip(), "", f"{k} v .env.example musí být prázdný")

    def test_gitignore_chrani_tajemstvi(self):
        with open(os.path.join(ROOT, ".gitignore"), encoding="utf-8") as f:
            gi = f.read()
        for vzor in (".env", "config.local.json", "data/"):
            self.assertIn(vzor, gi)


if __name__ == "__main__":
    unittest.main()
