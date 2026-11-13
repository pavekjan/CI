"""Odhad segmentu u zakazek bez CPV (ts/segmenty.py)."""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from ts import api, db, segmenty  # noqa: E402

VZORY = {
    "45": ["Rekonstrukce chodníku v ulici {}", "Stavební úpravy školy {}", "Oprava silnice III/{}"],
    "33": ["Dodávka léčivých přípravků {}", "Zdravotnický materiál pro nemocnici {}", "Katétry a stenty {}"],
    "30": ["Dodávka notebooků {}", "Výpočetní technika pro úřad {}", "Tiskárny a multifunkce {}"],
}


def _db():
    d = tempfile.mkdtemp()
    con = db.connect(os.path.join(d, "t.db"))
    i = 0
    for oddil, vzory in VZORY.items():
        for k in range(120):
            i += 1
            con.execute("INSERT INTO zakazky (id, nazev, druh, cpv_hlavni) VALUES (?,?,?,?)",
                        (f"z{i}", vzory[k % 3].format(k), "Dodávky", oddil + "100000"))
    con.executemany("INSERT INTO zakazky (id, nazev, druh, cpv_hlavni) VALUES (?,?,?,?)", [
        ("b1", "Rekonstrukce chodníku u nádraží", "Stavební práce", None),
        ("b2", "Dodávka léčivých přípravků 2027", "Dodávky", ""),
        ("b3", "Něco úplně jiného bez známých slov", "Služby", None),
        ("b4", "Dodávka notebooků pro školu", "Dodávky", "30213100"),  # uvedene CPV se nemeni
    ])
    con.commit()
    return con


class Odhad(unittest.TestCase):
    def test_odhad_podle_nazvu(self):
        con = _db()
        st = segmenty.klasifikuj(con)
        cpv = dict(con.execute("SELECT id, cpv_hlavni FROM zakazky WHERE id LIKE 'b%'").fetchall())
        self.assertEqual(cpv["b1"], "45")
        self.assertEqual(cpv["b2"], "33")
        self.assertIsNone(cpv["b3"])
        self.assertEqual(cpv["b4"], "30213100")
        self.assertEqual(st["neuvedeno"], 1)
        t = api.trh(con)
        seg = {s["segment"]: s for s in t["segmenty"]}
        self.assertEqual(seg["45 Stavební práce"]["odhad"], 1)
        self.assertEqual(seg["neuvedeno"]["pocet"], 1)
        self.assertEqual(segmenty.klasifikuj(con)["odhadnuto"], 2)  # opakovany beh je stejny

    def test_ai_jen_platne_oddily(self):
        con = _db()
        volano = []

        def ai(polozky):
            volano.append(polozky)
            return ["90" if "jiného" in n else None for n, _ in polozky]

        segmenty.klasifikuj(con, ai=ai)
        self.assertEqual(con.execute("SELECT cpv_hlavni, cpv_odhad FROM zakazky WHERE id='b3'").fetchone()[:], ("90", "ai"))
        self.assertEqual(len(volano), 1)
        self.assertEqual(len(volano[0]), 1)  # AI dostane jen zbytek, ktery neodhadl model

    def test_ai_klasifikator_overuje_vystup(self):
        from unittest import mock
        f = segmenty.ai_klasifikator({"typ": "openai"}, api.CPV_DIV)
        odp = {"oddily": [{"i": 0, "oddil": "45"}, {"i": 1, "oddil": "99"}, {"i": 7, "oddil": "33"}, {"i": "x", "oddil": "33"}]}
        with mock.patch("ts.llm.zavolej", return_value=(odp, {})):
            self.assertEqual(f([("a", "b"), ("c", "d")]), ["45", None])

    def test_chyba_ai_nic_nerozbije(self):
        con = _db()

        def ai(_):
            raise RuntimeError("limit")
        st = segmenty.klasifikuj(con, ai=ai)
        self.assertEqual(st["ai"], 0)

    def test_online_verze_ai_nepouzije(self):
        import server
        with mock_dict(server.SEC, verejne=True), mock_dict(server.STATE, ai_segmenty=400):
            self.assertIsNone(server._ai_pro_segmenty())


class mock_dict:
    def __init__(self, d, **kw):
        self.d, self.kw, self.old = d, kw, {}

    def __enter__(self):
        self.old = {k: self.d.get(k) for k in self.kw}
        self.d.update(self.kw)

    def __exit__(self, *a):
        self.d.update(self.old)


if __name__ == "__main__":
    unittest.main()


class OnboardingBezCPV(unittest.TestCase):
    """Chyba z online verze: firma, jejiz zakazky nemaji CPV (segment "neuvedeno"), shodila onboarding."""
    def test_start_a_dokonceni(self):
        from ts import onboarding
        from ts.util import load_config
        con = _db()
        for i in range(5):
            con.execute("INSERT INTO zakazky (id, nazev, druh, cpv_hlavni, zadavatel_ico, zadavatel_nazev) VALUES (?,?,?,?,?,?)",
                        (f"n{i}", f"Neco {i}", "Služby", None, "00064165", "Nemocnice"))
            con.execute("INSERT INTO vitezove (zakazka_id, dodavatel_ico, dodavatel_nazev, cena_bez_dph) VALUES (?,?,?,?)",
                        (f"n{i}", "60838744", "STRABAG a.s.", 1e6))
        con.commit()
        cfg = dict(load_config(), llm_vypnuto=True)
        r = onboarding.start(con, cfg, "60838744", None, online=False)
        self.assertTrue(r["faze1"])
        self.assertNotIn("neuvedeno", [s["segment"] for s in r["recon"]["historie"]["segmenty"]])
        self.assertIn("zpravodaj", onboarding.dokonci(con, cfg, "60838744", {}))


class Kvalifikace(unittest.TestCase):
    def test_obrat_a_reference(self):
        from ts import onboarding
        kap = {"verejne_trzby_12m": 30e6, "reference": {"45": [12e6, 15e6, 1e6]}}
        z = {"predpokladana_hodnota": 20e6, "cpv_hlavni": "45233000"}
        sk, odp, ko = onboarding._kvalifikace(z, {}, kap)
        self.assertIsNone(ko)
        self.assertGreaterEqual(sk, 70)          # 30 mil. >= 20 mil. a 2 srovnatelne reference
        sk2, _, ko2 = onboarding._kvalifikace({"predpokladana_hodnota": 500e6, "cpv_hlavni": "45000000"}, {"obrat_czk": 20e6}, kap)
        self.assertIsNotNone(ko2)                # zadany obrat 20 mil. vs. zakazka 500 mil. -> nedosahne
        _, _, ko3 = onboarding._kvalifikace({"predpokladana_hodnota": 500e6, "cpv_hlavni": "45000000"},
                                            {"obrat_czk": 20e6, "consortium_ok": True}, kap)
        self.assertIsNone(ko3)                   # s konsorciem se nevylucuje
        _, odp4, _ = onboarding._kvalifikace({"predpokladana_hodnota": 5e6, "min_obrat": 40e6, "kvalifikace": "obrat 40 mil."}, {}, kap)
        self.assertIn("zadavatel uvádí", odp4)
        self.assertIn("na hraně", odp4)          # zdroj uvadi pozadovany obrat 40 mil. > 30 mil.
