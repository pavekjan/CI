"""v13: odkazy a identifikatory zakazek, automaticke CPV z historie, spojity model skore, limity AI."""
import os
import sys
import tempfile
import unittest
from datetime import date, timedelta
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from ts import ai_limity, db, extractor, onboarding  # noqa: E402
from ts.odkazy import odkazy  # noqa: E402

DNES = date(2026, 11, 13)


class Odkazy(unittest.TestCase):
    def test_identifikatory_z_open_dat(self):
        rec = {"EvidencniCisloVZnaVVZ": "Z2026-027630", "NazevVZ": "Čistírna odpadních vod Příbram",
               "Poznamka": "Systémové číslo N006/26/V00015651, Identifikátor NIPEZ RVZ2600096641",
               "ZadavatelProfilURL": "https://nen.nipez.cz/profil/PRIBRAM",
               "Dodavatel": {"Poznamka": "RVZ2600000001"}}
        z, _, _ = extractor.extract(rec)
        self.assertEqual(z["vvz_cislo"], "Z2026-027630")
        self.assertEqual(z["nen_cislo"], "N006/26/V00015651")
        self.assertEqual(z["nipez_id"], "RVZ2600096641")      # ne cislo z bloku dodavatele
        self.assertEqual(z["profil_url"], "https://nen.nipez.cz/profil/PRIBRAM")

    def test_odkazy(self):
        o = odkazy({"id": "rvz:Z2026-033254", "nen_cislo": "N006/26/V00015651", "nazev": "X", "zadavatel_ico": "00243132"})
        self.assertEqual(o["url"], "https://nen.nipez.cz/verejne-zakazky/detail-zakazky/N006-26-V00015651")
        urls = [x["url"] for x in o["odkazy"]]
        self.assertIn("https://vvz.nipez.cz/formulare-zakazky/Z2026-033254", urls)
        self.assertIn("https://www.hlidacstatu.cz/subjekt/00243132", urls)
        self.assertEqual(o["vvz_cislo"], "Z2026-033254")

    def test_bez_cisel_aspon_hledani(self):
        o = odkazy({"id": "rvz:513238", "nazev": 'IKEM "Praha" – VZT', "zadavatel_ico": "00023001", "url": "javascript:alert(1)"})
        self.assertTrue(o["url"].startswith("https://www.hlidacstatu.cz/verejnezakazky/hledat?Q="))
        self.assertNotIn("javascript", " ".join(x["url"] for x in o["odkazy"]))


def _profil(**kw):
    p = {"ico": "1", "nazev": "Firma", "vertical": "stavebnictvi", "cpv_codes": {"main": ["45233000"], "secondary": []},
         "regions_nuts3": ["CZ064"], "sidlo": {"lat": 49.1951, "lon": 16.6068, "mesto": "Brno"}, "max_distance_km": 150,
         "budget": {"min_czk": 1e6, "max_czk": 20e6}, "min_prep_days": 10, "negative_keywords": []}
    p.update(kw)
    return p


def _z(**kw):
    z = {"id": "z", "nazev": "Oprava silnice", "cpv_hlavni": "45233000", "cpv": "45233000", "nuts": "CZ064", "kraj": "Jihomoravský",
         "predpokladana_hodnota": 5e6, "lhuta_nabidek": (DNES + timedelta(days=20)).isoformat(), "zadavatel_ico": "9"}
    z.update(kw)
    return z


def _v(z, p=None, klienti=None, konk=None):
    return onboarding.vhodnost(z, p or _profil(), None, {}, konk or {}, DNES, klienti or {}, {"reference": {}})


class Skore(unittest.TestCase):
    def test_nevhodne_uz_nemaji_vsechny_25(self):
        a = _v(_z(lhuta_nabidek=(DNES + timedelta(days=4)).isoformat()))              # malo casu, jinak sedi
        b = _v(_z(lhuta_nabidek=(DNES + timedelta(days=1)).isoformat(), predpokladana_hodnota=200e6))  # 2 srazky
        self.assertEqual(a["verdikt"], "nevhodné")
        self.assertEqual(b["verdikt"], "nevhodné")
        self.assertNotEqual(a["skore"], b["skore"])
        self.assertGreater(a["skore"], b["skore"])

    def test_rozpad_sedi(self):
        v = _v(_z())
        self.assertAlmostEqual(sum(c["body"] for c in v["kriteria"] if c["body"] is not None), v["zaklad"], delta=1)
        self.assertEqual(v["skore"], v["zaklad"])                                        # bez srazek
        self.assertTrue(0 <= v["skore"] <= 100)

    def test_monotonie(self):
        hodnoty = [_v(_z(predpokladana_hodnota=h))["kriteria"][2]["skore"] for h in (10e6, 30e6, 60e6, 120e6)]
        self.assertEqual(hodnoty, sorted(hodnoty, reverse=True))                           # cim vic nad rozsahem, tim hur
        casy = [_v(_z(lhuta_nabidek=(DNES + timedelta(days=d)).isoformat()))["skore"] for d in (2, 5, 10, 30)]
        self.assertEqual(casy, sorted(casy))
        zad = [_v(_z(), klienti={"9": n})["kriteria"][4]["skore"] for n in (0, 1, 3)]
        self.assertEqual(zad, sorted(zad))
        konk = [_v(_z(), konk={"45": {"prumer_nabidek": n, "top_podil": 0.2}})["skore"] for n in (1, 3, 6)]
        self.assertEqual(konk, sorted(konk, reverse=True))

    def test_daleko(self):
        blizko = _v(_z())
        daleko = _v(_z(nuts="CZ041", kraj="Karlovarský"))                                  # Karlovy Vary ~ 380 km
        self.assertGreater(blizko["kriteria"][1]["skore"], daleko["kriteria"][1]["skore"])
        self.assertTrue(any(s["klic"] == "lokalita" for s in daleko["srazky"]))


class AutoCPV(unittest.TestCase):
    def test_z_vyher_nabidek_a_smluv(self):
        con = db.connect(os.path.join(tempfile.mkdtemp(), "t.db"))
        for i in range(30):
            con.execute("INSERT INTO zakazky (id, nazev, druh, cpv_hlavni) VALUES (?,?,?,?)",
                        (f"t{i}", f"Dodávka notebooků {i}", "Dodávky", "30213100"))
        con.execute("INSERT INTO zakazky (id, nazev, cpv_hlavni, predpokladana_hodnota) VALUES ('w1','Notebooky','30213100',9e6)")
        con.execute("INSERT INTO zakazky (id, nazev, cpv_hlavni, predpokladana_hodnota) VALUES ('w2','Tiskárny','30232110',1e6)")
        con.execute("INSERT INTO zakazky (id, nazev, cpv_hlavni) VALUES ('u1','Monitory','30231300')")
        for zid in ("w1", "w2"):
            con.execute("INSERT INTO vitezove (zakazka_id, dodavatel_ico) VALUES (?, '27082440')", (zid,))
        con.execute("INSERT INTO ucastnici (zakazka_id, dodavatel_ico) VALUES ('u1', '27082440')")
        for i in range(3):  # obor jen ze smluv se pocita az od 3 smluv
            con.execute("INSERT INTO smlouvy (id, predmet) VALUES (?, ?)", (f"s{i}", f"Dodávka notebooků pro školu {i}"))
            con.execute("INSERT INTO smlouvy_strany (smlouva_id, ico) VALUES (?, '27082440')", (f"s{i}",))
        vyhry = [dict(r) | {"cena_bez_dph": None} for r in con.execute("SELECT * FROM zakazky WHERE id IN ('w1','w2')")]
        r = onboarding.auto_cpv(con, "27082440", vyhry)
        kody = [c["cpv"] for c in r["top_cpv"]]
        self.assertEqual(kody[0], "30213100")                 # nejvetsi objem vyher
        self.assertIn("30231300", kody)                       # podana nabidka
        self.assertIn("30000000", kody)                       # obor ze smlouvy v Registru
        self.assertIn("vyhraných zakázek", r["cpv_zdroj"])


class LimityAI(unittest.TestCase):
    def setUp(self):
        ai_limity.reset_pro_testy()

    def test_openrouter_free_20_za_minutu(self):
        n = {"prov": "openrouter", "nazev": "OpenRouter", "model": "openrouter/free", "klic": "k"}
        self.assertEqual(ai_limity.limity(n)["rpm"], 20)
        self.assertEqual([ai_limity.pred_volanim(n) is None for _ in range(21)], [True] * 20 + [False])

    def test_429_kratce_pocka_denni_pozastavi(self):
        n = {"prov": "groq", "nazev": "Groq", "model": "x", "klic": "k"}
        self.assertEqual(ai_limity.po_chybe(n, 429, {"retry-after": "3"}, "", 0), 3)
        self.assertIsNone(ai_limity.po_chybe(n, 429, {"x-ratelimit-reset": "2h0m0s"}, "rate limit per day", 0))
        self.assertIn("denní", ai_limity.pred_volanim(n))
        self.assertIsNotNone(ai_limity.stav(n)["pauza"])

    def test_402_pozastavi(self):
        n = {"prov": "openrouter", "nazev": "OpenRouter", "model": "openai/gpt-5", "klic": "k"}
        self.assertIsNone(ai_limity.po_chybe(n, 402, {}, '{"error":{"code":402}}', 0))
        self.assertIn("kredit", ai_limity.pred_volanim(n))

    def test_hlavicky(self):
        n = {"prov": "groq", "nazev": "Groq", "model": "x", "klic": "k"}
        ai_limity.po_odpovedi(n, {"x-ratelimit-remaining-requests": "14370", "x-ratelimit-limit-requests": "14400",
                                  "x-ratelimit-reset-requests": "2m59.56s", "x-ratelimit-remaining-tokens": "17997"})
        h = ai_limity.stav(n)["hlavicky"]
        self.assertEqual((h["zbyva_dotazu"], h["limit_dotazu"], h["zbyva_tokenu"]), (14370, 14400, 17997))
        self.assertAlmostEqual(h["reset_s"], 179.56, places=1)

    def test_zivy_openrouter(self):
        n = {"prov": "openrouter", "nazev": "OpenRouter", "model": "openrouter/free", "klic": "k"}
        r = mock.Mock(status_code=200, json=lambda: {"data": {"free_model_daily_requests": {"used": 50, "limit": 50, "remaining": 0}}})
        z = ai_limity.zivy_stav(n, lambda *a, **k: r)
        self.assertEqual(z["denni_zbyva"], 0)
        self.assertIsNotNone(ai_limity.pred_volanim(n))       # dnes uz nevolat -> pravidla

    def test_vychozi_strop_aplikace(self):
        import server
        self.assertIsNone(server.ai_limit({"llm_poskytovatel": "groq"}))                          # zdarma: bez limitu
        self.assertIsNone(server.ai_limit({"llm_poskytovatel": "openrouter", "openrouter_model": "openrouter/free"}))
        self.assertEqual(server.ai_limit({"llm_poskytovatel": "openai"}), 30)                       # placene: 30
        self.assertIsNone(server.ai_limit({"llm_poskytovatel": "openai", "ai_denni_limit": 0}))     # 0 = bez limitu
        self.assertEqual(server.ai_limit({"llm_poskytovatel": "groq", "ai_denni_limit": 100}), 100)


if __name__ == "__main__":
    unittest.main()
