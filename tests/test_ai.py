"""Testy vyberu AI poskytovatele (bez internetu: falesne OpenAI-kompatibilni API na localhostu).

Overuje, ze:
- volani OpenAI-kompatibilniho API funguje a umi ustoupit, kdyz model nezna JSON schema
- chyba klice se ukaze srozumitelne a klic se nikde neobjevi
- navstevnik online verze bez hesla AI nikdy nespusti (nic neplati)
- denni limit volani AI plati
- na online verzi nejde nastavit adresu API do vnitrni site (SSRF) a nacist modely bez hesla
"""
import json
import os
import sys
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from test_bezpecnost import HESLO, jj, spust_server, zavolej  # noqa: E402
from ts import llm  # noqa: E402

KLIC = "test-klic-0123456789abcdef"


class FalesneAPI:
    """Mini server, ktery se tvari jako OpenAI /v1/chat/completions a /v1/models."""

    def __init__(self, umi_schema=True, klic=KLIC):
        self.volani, self.umi_schema, self.klic = [], umi_schema, klic
        api = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _odpoved(self, kod, obj):
                b = json.dumps(obj).encode()
                self.send_response(kod)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(b)))
                self.end_headers()
                self.wfile.write(b)

            def _auth(self):
                if self.headers.get("Authorization") != f"Bearer {api.klic}":
                    self._odpoved(401, {"error": {"message": "Incorrect API key"}})
                    return False
                return True

            def do_GET(self):
                if self._auth():
                    self._odpoved(200, {"data": [{"id": "model-b"}, {"id": "models/model-a"}]})

            def do_POST(self):
                telo = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                if not self._auth():
                    return
                api.volani.append(telo)
                rf = (telo.get("response_format") or {}).get("type")
                if rf == "json_schema" and not api.umi_schema:
                    return self._odpoved(400, {"error": {"message": "response_format json_schema not supported"}})
                obsah = {"status": "needs_clarification", "detected_summary": "Shrnutí od testovací AI",
                         "detected_vertical": "jine", "questions": [], "ok": True, "pozdrav": "Ahoj"}
                self._odpoved(200, {"model": telo["model"], "choices": [{"finish_reason": "stop", "message": {
                    "content": "```json\n" + json.dumps(obsah, ensure_ascii=False) + "\n```"}}],
                    "usage": {"prompt_tokens": 10, "completion_tokens": 5}})

        self.srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.url = f"http://127.0.0.1:{self.srv.server_address[1]}/v1"
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()

    def stop(self):
        self.srv.shutdown()
        self.srv.server_close()


def chat_volani(api):
    return [v for v in api.volani if "messages" in v]


class Volani(unittest.TestCase):
    def test_openai_kompatibilni_api(self):
        api = FalesneAPI()
        try:
            n = llm.nastaveni({"llm_poskytovatel": "vlastni", "vlastni_url": api.url, "vlastni_api_key": KLIC,
                               "vlastni_model": "muj-model"})
            d, info = llm.zavolej(n, {"x": 1}, llm.SCHEMA_FAZE1)
            self.assertEqual(d["detected_summary"], "Shrnutí od testovací AI")
            self.assertEqual(info["vstup_tokenu"], 10)
            self.assertEqual(api.volani[0]["response_format"]["type"], "json_schema")
            self.assertEqual(llm.modely(n), ["model-a", "model-b"])
        finally:
            api.stop()

    def test_model_bez_json_schema_ustoupi(self):
        api = FalesneAPI(umi_schema=False)
        try:
            n = llm.nastaveni({"llm_poskytovatel": "vlastni", "vlastni_url": api.url, "vlastni_api_key": KLIC,
                               "vlastni_model": "slabsi-model"})
            d, _ = llm.zavolej(n, {"x": 1}, llm.SCHEMA_FAZE1)
            self.assertEqual(d["detected_vertical"], "jine")
            self.assertEqual([v.get("response_format", {}).get("type") for v in api.volani], ["json_schema", "json_object"])
        finally:
            api.stop()

    def test_spatny_klic_srozumitelne_a_bez_klice(self):
        api = FalesneAPI()
        try:
            spatny = "spatny-klic-tajny-999999"
            n = llm.nastaveni({"llm_poskytovatel": "vlastni", "vlastni_url": api.url, "vlastni_api_key": spatny,
                               "vlastni_model": "m"})
            with self.assertRaises(llm.LLMChyba) as e:
                llm.zavolej(n, {"x": 1}, llm.SCHEMA_FAZE1)
            self.assertIn("neplatný API klíč", str(e.exception))
            self.assertNotIn(spatny, str(e.exception))
        finally:
            api.stop()

    def test_bez_klice_neni_ai(self):
        for prov in ("anthropic", "openai", "gemini", "mistral", "openrouter"):
            self.assertIsNone(llm.nastaveni({"llm_poskytovatel": prov}), prov)
        self.assertIsNotNone(llm.nastaveni({"llm_poskytovatel": "ollama"}), "Ollama klíč nepotřebuje")
        self.assertIsNone(llm.nastaveni({"llm_poskytovatel": "openai", "openai_api_key": "x", "llm_vypnuto": True}))


class BezplatnePredvolby(unittest.TestCase):
    """Adresy overene podle github.com/mnfst/awesome-free-llm-apis (data.json, 2026-11-11)."""

    OVERENE = {
        "groq": "https://api.groq.com/openai/v1",
        "openrouter_free": "https://openrouter.ai/api/v1",
        "cloudflare": "https://api.cloudflare.com/client/v4/accounts/{account_id}/ai/v1",
        "cohere": "https://api.cohere.ai/compatibility/v1",
        "zai": "https://api.z.ai/api/paas/v4",
        "nvidia": "https://integrate.api.nvidia.com/v1",
        "gonka": "https://proxy.gonkabroker.com/v1",
        "ovh": "https://oai.endpoints.kepler.ai.cloud.ovh.net/v1",
        "kilo": "https://api.kilo.ai/api/gateway",
        "llm7": "https://api.llm7.io/v1",
        "gemini": "https://generativelanguage.googleapis.com/v1beta/openai",
    }

    def test_adresy(self):
        for prov, url in self.OVERENE.items():
            self.assertEqual(llm.POSKYTOVATELE[prov]["url"], url, prov)
            self.assertTrue(llm.POSKYTOVATELE[prov]["zdarma"], prov)

    def test_jen_https_a_zadne_cinske_overeni(self):
        for prov, p in llm.POSKYTOVATELE.items():
            if p["url"] and prov != "ollama":
                self.assertTrue(p["url"].startswith("https://"), prov)
        for vynechany in ("modelscope", "siliconflow"):
            self.assertNotIn(vynechany, llm.POSKYTOVATELE)

    def test_bez_klice(self):
        for prov in ("ovh", "kilo", "llm7"):
            n = llm.nastaveni({"llm_poskytovatel": prov})
            self.assertIsNotNone(n, prov)
            self.assertEqual(n["klic"], "")
        for prov in ("groq", "cohere", "zai", "nvidia", "gonka", "openrouter_free", "gemini"):
            self.assertIsNone(llm.nastaveni({"llm_poskytovatel": prov}), f"{prov} potřebuje klíč")

    def test_cloudflare_account_id(self):
        cfg = {"llm_poskytovatel": "cloudflare", "cloudflare_api_key": "tok"}
        self.assertIsNone(llm.nastaveni(cfg), "bez Account ID nejde")
        self.assertIsNone(llm.nastaveni(dict(cfg, cloudflare_ucet="../../evil")))
        n = llm.nastaveni(dict(cfg, cloudflare_ucet="0123456789abcdef0123456789abcdef"))
        self.assertEqual(n["url"], "https://api.cloudflare.com/client/v4/accounts/0123456789abcdef0123456789abcdef/ai/v1")

    def test_predvolbe_nejde_podstrcit_adresu(self):
        """Adresa predvoleneho poskytovatele je pevna, zmenit jde jen u Ollamy a vlastniho API."""
        n = llm.nastaveni({"llm_poskytovatel": "groq", "groq_api_key": "k", "groq_url": "http://169.254.169.254"})
        self.assertEqual(n["url"], "https://api.groq.com/openai/v1")


class OnlineVerzeAI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.api = FalesneAPI()
        cls.proc, cls.url = spust_server({
            "TS_VEREJNE": "1", "TS_ADMIN_HESLO": HESLO, "TS_LIMIT_LLM_DEN": "2",
            "TS_LIMIT_ZA_MINUTU": "1000", "TS_LIMIT_DRAHE_ZA_MINUTU": "1000",
            "LLM_POSKYTOVATEL": "vlastni", "LLM_URL": cls.api.url, "LLM_API_KEY": KLIC, "LLM_MODEL": "muj-model"})
        import demo
        cls.ico = demo.FIRMY[1][0]

    @classmethod
    def tearDownClass(cls):
        cls.proc.kill(); cls.proc.wait(); cls.proc.stdout.close()
        cls.api.stop()

    def test_1_navstevnik_ai_nespusti(self):
        kod, raw, _ = zavolej(self.url, "/api/onboarding/start", "POST", {"ico": self.ico}, {"X-Uzivatel": "f" * 32})
        self.assertEqual(kod, 200, raw)
        self.assertEqual(jj(raw)["agent"]["rezim"], "pravidla")
        self.assertEqual(chat_volani(self.api), [], "návštěvník bez hesla nesmí volat placenou AI")

    def test_2_spravce_ai_pouzije_a_limit_plati(self):
        h = {"X-Admin-Heslo": HESLO}
        kod, raw, _ = zavolej(self.url, "/api/onboarding/start", "POST", {"ico": self.ico}, h)
        self.assertEqual(kod, 200, raw)
        d = jj(raw)
        self.assertEqual(d["agent"]["rezim"], "llm")
        self.assertEqual(d["faze1"]["detected_summary"], "Shrnutí od testovací AI")
        self.assertEqual(len(d["faze1"]["questions"]), 4, "chybějící otázky doplní pravidla")
        zavolej(self.url, "/api/onboarding/start", "POST", {"ico": self.ico}, h)   # 2. volani = limit 2
        kod, raw, _ = zavolej(self.url, "/api/onboarding/start", "POST", {"ico": self.ico}, h)
        self.assertEqual(jj(raw)["agent"]["rezim"], "pravidla")
        self.assertIn("limit", jj(raw)["agent"]["duvod"])
        self.assertEqual(len(chat_volani(self.api)), 2)

    def test_modely_jen_pro_spravce(self):
        self.assertEqual(zavolej(self.url, "/api/ai/modely", "POST", {})[0], 403)
        self.assertEqual(zavolej(self.url, "/api/ai/test", "POST", {})[0], 403)
        kod, raw, _ = zavolej(self.url, "/api/ai/modely", "POST", {}, {"X-Admin-Heslo": HESLO})
        self.assertEqual(kod, 200, raw)
        self.assertIn("model-a", jj(raw)["modely"])

    def test_ssrf_adresa_api_na_online_verzi(self):
        h = {"X-Admin-Heslo": HESLO}
        for url in ["http://127.0.0.1:11434/v1", "https://169.254.169.254/v1", "http://example.com/v1", "file:///etc/passwd"]:
            kod, raw, _ = zavolej(self.url, "/api/nastaveni", "POST", {"llm_poskytovatel": "vlastni", "llm_url": url}, h)
            self.assertEqual(kod, 400, url)

    def test_neznamy_poskytovatel_a_model(self):
        h = {"X-Admin-Heslo": HESLO}
        self.assertEqual(zavolej(self.url, "/api/ai/modely", "POST", {"llm_poskytovatel": "../../etc"}, h)[0], 400)
        self.assertEqual(zavolej(self.url, "/api/ai/test", "POST", {"llm_model": "x; rm -rf /"}, h)[0], 400)

    def test_cloudflare_spatne_account_id(self):
        kod, _, _ = zavolej(self.url, "/api/ai/modely", "POST",
                            {"llm_poskytovatel": "cloudflare", "llm_ucet": "../x", "llm_klic": "tok"}, {"X-Admin-Heslo": HESLO})
        self.assertEqual(kod, 400)

    def test_navstevnik_nevidi_account_id(self):
        kod, raw, _ = zavolej(self.url, "/api/nastaveni")
        for p in jj(raw)["ai"]["poskytovatele"]:
            self.assertEqual(p["ucet"], "", p["id"])

    def test_klic_se_nikde_neukaze(self):
        for hl in ({}, {"X-Admin-Heslo": HESLO}):
            kod, raw, _ = zavolej(self.url, "/api/nastaveni", hlavicky=hl)
            self.assertNotIn(KLIC.encode(), raw)
            self.assertNotIn(KLIC[6:].encode(), raw)
        kod, raw, _ = zavolej(self.url, "/api/beh")
        self.assertNotIn(KLIC.encode(), raw)


if __name__ == "__main__":
    unittest.main()
