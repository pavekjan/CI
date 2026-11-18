"""v21: hledani firmy podle nazvu / webu, CI analyza a otazky podlozene daty."""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ts import najdi, onboarding  # noqa: E402


class Najdi(unittest.TestCase):
    def test_kontrolni_soucet_ico(self):
        self.assertTrue(najdi.ico_platne("27082440"))   # Alza
        self.assertTrue(najdi.ico_platne("60838744"))   # Strabag
        self.assertFalse(najdi.ico_platne("27082441"))
        self.assertFalse(najdi.ico_platne("123"))

    def test_ico_z_html(self):
        html = """<footer>Alza.cz a.s., IČO: 270 82 440, DIČ: CZ27082440<br>tel. 225 340 111
                  <p>IC:60838744</p><p>Identifikační číslo 12345678</p></footer>"""
        self.assertEqual(najdi.ica_z_html(html), ["27082440", "60838744"])  # 12345678 nema platny soucet

    def test_je_web_a_kmen(self):
        self.assertTrue(najdi.je_web("www.alza.cz"))
        self.assertTrue(najdi.je_web("https://stavby-novak.cz/kontakt"))
        self.assertFalse(najdi.je_web("Alza.cz a.s."))
        self.assertFalse(najdi.je_web("27082440"))
        self.assertEqual(najdi.kmen_domeny("https://www.alza.cz/kontakt"), "alza")
        self.assertEqual(najdi.kmen_domeny("stavby-novak.cz"), "stavby novak")


class Otazky(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import demo
        from ts.db import connect
        cls.tmp = tempfile.mkdtemp()
        cls.path = os.path.join(cls.tmp, "t.db")
        demo.build_demo_db(cls.path)
        cls.con = connect(cls.path)
        cls.ico = cls.con.execute("SELECT dodavatel_ico FROM vitezove GROUP BY dodavatel_ico ORDER BY COUNT(*) DESC LIMIT 1").fetchone()[0]

    def test_najdi_lokalne_podle_nazvu(self):
        nazev = self.con.execute("SELECT nazev FROM dodavatele WHERE ico=?", (self.ico,)).fetchone()[0]
        r = najdi.najdi(self.con, nazev.split()[0], None, online=False)
        self.assertEqual(r["typ"], "nazev")
        self.assertIn(self.ico, [k["ico"] for k in r["kandidati"]])
        r = najdi.najdi(self.con, self.ico, None, online=False)
        self.assertEqual((r["typ"], r["kandidati"][0]["ico"]), ("ico", self.ico))

    def test_sest_otazek_s_dukazy(self):
        rc = onboarding.recon(self.con, {"zdroje": {"ares_base": "x"}}, self.ico, online=False)
        self.assertIn("ci", rc)
        f1 = onboarding.faze1_pravidla(rc)
        ids = [q["id"] for q in f1["questions"]]
        self.assertEqual(ids, ["q1_scope", "q5_strategy", "q6_competitors", "q2_budget", "q2_prep", "q3_region", "q4_qualification"])
        for q in f1["questions"]:
            self.assertTrue(q["proc"])
            self.assertIsInstance(q["evidence"], list)

    def test_ai_nesmi_vymyslet_konkurenty(self):
        rc = onboarding.recon(self.con, {"zdroje": {"ares_base": "x"}}, self.ico, online=False)
        z = onboarding.faze1_pravidla(rc)
        d = {"questions": [{"id": "q6_competitors", "question_text": "?", "quick_replies": ["Vymyšlená s.r.o."]},
                           {"id": "q5_strategy", "question_text": "Jiný text", "quick_replies": ["A", "B"]}]}
        out = onboarding._ocisti_faze1(d, z)
        q = {x["id"]: x for x in out["questions"]}
        self.assertEqual(q["q6_competitors"]["quick_replies"], z["questions"][2]["quick_replies"])
        self.assertEqual(q["q5_strategy"]["question_text"], "Jiný text")
        self.assertEqual(q["q5_strategy"]["evidence"], z["questions"][1]["evidence"])  # dukazy jen z dat

    def test_strategie_a_sledovani_v_profilu(self):
        rc = onboarding.recon(self.con, {"zdroje": {"ares_base": "x"}}, self.ico, online=False)
        f1 = onboarding.faze1_pravidla(rc)
        q6 = f1["questions"][2]["quick_replies"]
        odp = {"q5_strategy": {"vybrano": ["Získat nové zadavatele ve svém oboru"], "text": ""},
               "q6_competitors": {"vybrano": q6[:1], "text": "a taky 27082440"}}
        p = onboarding.faze2_pravidla(rc, f1, odp)["company_profile"]
        self.assertEqual(p["strategy"], "novi_zadavatele")
        icos = [w["ico"] for w in p["watchlist"]]
        self.assertIn("27082440", icos)
        if (rc["ci"]["souboje"] or rc["ci"]["lidri"]) and not q6[0].startswith("Zatím"):
            self.assertGreaterEqual(len(icos), 2)
        z = onboarding.zpravodaj(self.con, onboarding._ocisti_profil(p, {"company_profile": p}, rc))
        for x in z["polozky"]:
            self.assertIn("sledovani", x)


    def test_nace_nepridava_obory_firme_s_historii(self):
        """ARES zivnosti (napr. stravovani u e-shopu) nesmi do profilu, kdyz firma ma vlastni historii zakazek."""
        rc = onboarding.recon(self.con, {"zdroje": {"ares_base": "x"}}, self.ico, online=False)
        rc["ares"] = {**(rc.get("ares") or {}), "nace": "56100,49410"}
        f1 = onboarding.faze1_pravidla(rc)
        p = onboarding.faze2_pravidla(rc, f1, {})["company_profile"]
        if sum(c["pocet"] for c in rc["historie"]["top_cpv"]) >= 5:
            vse = p["cpv_codes"]["main"] + p["cpv_codes"]["secondary"]
            self.assertFalse([c for c in vse if c[:2] in ("55", "60")], vse)

    def test_strategie_nove_zakazniky(self):
        rc = onboarding.recon(self.con, {"zdroje": {"ares_base": "x"}}, self.ico, online=False)
        f1 = onboarding.faze1_pravidla(rc)
        p = onboarding.faze2_pravidla(rc, f1, {"q5_strategy": {"vybrano": [f1["questions"][1]["quick_replies"][1]], "text": ""}})
        self.assertEqual(p["company_profile"]["strategy"], "novi_zadavatele")


class CiziMena(unittest.TestCase):
    def test_hodnota_v_cizi_mene(self):
        from ts.sources.smlouvy import hodnota_kc
        self.assertEqual(hodnota_kc({"hodnota_bez_dph": 100.0, "cizi_mena": (5.0, "EUR")}), 100.0)
        self.assertAlmostEqual(hodnota_kc({"hodnota_bez_dph": None, "hodnota_s_dph": 121.0}), 100.0)
        self.assertEqual(hodnota_kc({"hodnota_bez_dph": None, "hodnota_s_dph": None, "cizi_mena": (1000.0, "EUR")}), 25000.0)
        self.assertEqual(hodnota_kc({"hodnota_bez_dph": None, "hodnota_s_dph": None, "cizi_mena": (1000.0, "XYZ")}), 0.0)


if __name__ == "__main__":
    unittest.main()
