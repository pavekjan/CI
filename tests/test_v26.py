"""v26: kdo firma je (lidsky), otazky podle typu firmy, Porterovych 5 sil, odhad oboru bez zkresleni malych trid."""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ts import onboarding, segmenty  # noqa: E402


def _rc(segmenty_, typy=(), vyher=100):
    """Minimalni recon pro pravidla faze 1 (bez databaze)."""
    seg = [{"segment": f"{k} {onboarding.CPV_DIV.get(k, '')}", "pocet": n} for k, n in segmenty_]
    return {"ico": "12345678", "nazev": "Test s.r.o.", "ares": {}, "sidlo": {"kraj": "Hlavní město Praha", "nuts3": "CZ010"},
            "web": None, "ci": {},
            "historie": {"vyher": vyher, "ucasti": 0, "objem_czk": 1e8, "median_zakazky_czk": 4e5, "p25_czk": 1e5,
                         "p75_czk": 8e5, "p90_czk": 2e6, "max_czk": 1e7, "segmenty": seg,
                         "top_cpv": [{"cpv": k + "000000", "pocet": n, "segment": f"{k} x"} for k, n in segmenty_],
                         "top_zadavatele": [], "kraje": [], "typy_zakazniku": [{"typ": t, "pocet": 5} for t in typy],
                         "nazvy_vyher": [], "registr_smluv": {"pocet": 0, "objem_czk": 0, "predmety": [], "top_smluvni_partneri": []}}}


class Identita(unittest.TestCase):
    def test_potraviny_lidsky(self):
        rc = _rc([("15", 97), ("39", 3)], typy=["nemocnice a zdravotnictví", "armáda"])
        f1 = onboarding.faze1_pravidla(rc)
        shr = f1["detected_summary"]
        self.assertIn("prodává státu hlavně potraviny a nápoje", shr)
        self.assertIn("97 %", shr)
        self.assertIn("nemocnice a zdravotnictví; armáda", shr)
        for zkratka in ("CPV", "NACE", "RVZ", "VZMR"):
            self.assertNotIn(zkratka, shr)

    def test_zbozi_ma_otazky_o_dodani_ne_o_bodyshoppingu(self):
        f1 = onboarding.faze1_pravidla(_rc([("30", 60), ("32", 40)]))
        self.assertEqual(f1["detected_vertical"], "dodavky_zbozi")  # pocitace = zbozi, ne IT sluzby
        q = {x["id"]: x for x in f1["questions"]}
        self.assertEqual(q["q3_region"]["question_text"], "Kam jste schopni zboží dovézt?")
        self.assertFalse(any("bodyshop" in o for o in q["q3_region"]["quick_replies"]))
        self.assertTrue(any("servis" in o for o in q["q4_qualification"]["quick_replies"]))

    def test_nechceme_neodporuje_nabidce(self):
        f1 = onboarding.faze1_pravidla(_rc([("34", 30), ("50", 7), ("45", 4)]))
        q1 = f1["questions"][0]["quick_replies"]
        self.assertIn("Stavební práce", q1)
        self.assertNotIn("Nechceme: stavební práce", q1)

    def test_zbozi_kamkoli_v_cesku(self):
        rc = _rc([("15", 50)])
        f1 = onboarding.faze1_pravidla(rc)
        p = onboarding.faze2_pravidla(rc, f1, {"q3_region": {"vybrano": ["Dovezeme kamkoli v Česku"], "text": ""}})["company_profile"]
        self.assertEqual((p["regions_nuts3"], p["max_distance_km"]), (["CZ0"], None))

    def test_typ_zakaznika(self):
        self.assertEqual(onboarding.typ_zakaznika("Krajská nemocnice Liberec, a.s."), "nemocnice a zdravotnictví")
        self.assertEqual(onboarding.typ_zakaznika("Vězeňská služba České republiky"), "policie, hasiči, vězeňství a justice")
        self.assertEqual(onboarding.typ_zakaznika("Město Ždírec nad Doubravou"), "obce a města")


class Srozumitelnost(unittest.TestCase):
    def test_dny_jsou_samostatna_otazka(self):
        rc = _rc([("15", 50)])
        f1 = onboarding.faze1_pravidla(rc)
        q = {x["id"]: x for x in f1["questions"]}
        self.assertFalse(any("dní" in o for o in q["q2_budget"]["quick_replies"]))
        p = onboarding.faze2_pravidla(rc, f1, {"q2_prep": {"vybrano": ["Aspoň 15 dní"], "text": ""}})["company_profile"]
        self.assertEqual(p["min_prep_days"], 15)
        # stary format (dny v otazce na velikost) dal funguje
        p = onboarding.faze2_pravidla(rc, f1, {"q2_budget": {"vybrano": ["Na nabídku potřebujeme aspoň 10 dní"], "text": ""}})["company_profile"]
        self.assertEqual(p["min_prep_days"], 10)

    def test_jako_dosud_odpovida_dukazu(self):
        rc = _rc([("15", 50)])
        rc["historie"]["p10_czk"] = 52_300
        q2 = {x["id"]: x for x in onboarding.faze1_pravidla(rc)["questions"]}["q2_budget"]
        rozpeti = q2["quick_replies"][0].split(": ", 1)[1]
        self.assertIn(rozpeti, q2["evidence"][0]["text"])


class Porter(unittest.TestCase):
    def test_pet_sil_z_dat(self):
        import demo
        from ts.db import connect
        path = os.path.join(tempfile.mkdtemp(), "t.db")
        demo.build_demo_db(path)
        con = connect(path)
        ico = con.execute("SELECT dodavatel_ico FROM vitezove GROUP BY dodavatel_ico ORDER BY COUNT(*) DESC LIMIT 1").fetchone()[0]
        rc = onboarding.recon(con, {"zdroje": {"ares_base": "x"}}, ico, online=False)
        p = rc["ci"]["porter"]
        if p is None:
            self.skipTest("demo data maji v oboru malo soutezi")
        sily = [s["sila"] for s in p["sily"]]
        self.assertEqual(len(sily), len(set(sily)))
        self.assertIn("Hrozba náhražek (substitutů)", sily)
        uvahy = [s for s in p["sily"] if s["zdroj"] == "úvaha"]
        self.assertTrue(all(s["hodnoceni"] == "posuďte sami" for s in uvahy))  # odhad se netvari jako fakt


class OdhadOboru(unittest.TestCase):
    def test_mala_trida_nevyhrava_u_neznamych_slov(self):
        m = segmenty.Model()
        for i in range(2000):
            m.uc(f"Náhradní díly pro vozy řady {i}", "Dodávky", "70994226", "34")
            m.uc(f"Oprava vozů a lokomotiv {i}", "Služby", "70994226", "50")
        for i in range(25):
            m.uc(f"Dodávky barelové vody {i}", "Dodávky", "111", "41")
        y, _ = m.odhad("Náhradní díly dveří pro vozy ComfortJet", "Dodávky", "70994226")
        self.assertEqual(y, "34")
        y, _ = m.odhad("Dodávky barelové vody pro úřad", "Dodávky", "222")
        self.assertEqual(y, "41")


if __name__ == "__main__":
    unittest.main()
