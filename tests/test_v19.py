"""v19: prehledy trhu se predpocitaji (tabulka cache), online verze na slabem serveru je jen nacte."""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import demo  # noqa: E402
from ts import api  # noqa: E402
from ts.db import connect  # noqa: E402
from ts.util import load_config  # noqa: E402


class Predpocet(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.path = os.path.join(tempfile.mkdtemp(), "demo.db")
        demo.build_demo_db(cls.path)
        cls.con = connect(cls.path)
        cls.cfg = load_config()

    def setUp(self):
        api.smaz_cache(self.con)

    def test_trh_stejny_s_cache_i_bez(self):
        bez = api.trh(self.con)
        self.assertGreater(bez["zakazek"], 0)
        api._PAMET.clear()
        s_cache = api.trh(self.con)                      # ted uz z tabulky cache
        self.assertEqual(bez, s_cache)
        seg = bez["segmenty"][0]["segment"]
        self.assertEqual(api.trh(self.con, seg)["zakazek"], bez["segmenty"][0]["pocet"])

    def test_profil_z_predpoctu(self):
        ico = self.con.execute("SELECT dodavatel_ico FROM vitezove GROUP BY dodavatel_ico ORDER BY COUNT(*) DESC LIMIT 1").fetchone()[0]
        p1 = api.profil(self.con, ico, self.cfg, online=False)
        api.predpocitat(self.con)
        api._PAMET.clear()
        p2 = api.profil(self.con, ico, self.cfg, online=False)
        self.assertEqual(p1["skore"]["celkem"], p2["skore"]["celkem"])
        self.assertTrue(p2["segmenty"][0]["poradi"] >= 1)
        self.assertGreater(self.con.execute("SELECT COUNT(*) FROM cache").fetchone()[0], 2)

    def test_cisty_nazev(self):
        self.assertEqual(api.cisty_nazev("S u b t e r r a a.s."), "Subterra a.s.")
        self.assertEqual(api.cisty_nazev("M - SILNICE a.s."), "M - SILNICE a.s.")

    def test_sloucit_duplicity(self):
        con = connect(os.path.join(tempfile.mkdtemp(), "d.db"))
        for zid in ("rvz:RVZ1:aa", "rvz:Z2025-000001:aa", "rvz:RVZ2:bb"):
            con.execute("INSERT INTO zakazky (id, nazev, zadavatel_ico) VALUES (?, ?, '1')",
                        (zid, "Most" if zid.endswith("aa") else "Most"))
        con.execute("INSERT INTO vitezove (zakazka_id, dodavatel_ico, cena_bez_dph) VALUES ('rvz:RVZ1:aa', '9', 100)")
        con.execute("INSERT INTO vitezove (zakazka_id, dodavatel_ico, cena_bez_dph) VALUES ('rvz:Z2025-000001:aa', '9', 100)")
        con.execute("INSERT INTO vitezove (zakazka_id, dodavatel_ico, cena_bez_dph) VALUES ('rvz:RVZ2:bb', '9', 555)")
        con.execute("INSERT INTO ucastnici (zakazka_id, dodavatel_ico) VALUES ('rvz:RVZ1:aa', '8')")
        self.assertEqual(api.sloucit_duplicity(con), 1)
        ids = {r[0] for r in con.execute("SELECT id FROM zakazky")}
        self.assertEqual(ids, {"rvz:Z2025-000001:aa", "rvz:RVZ2:bb"})          # jina cena = jina zakazka
        self.assertEqual(con.execute("SELECT zakazka_id FROM ucastnici").fetchone()[0], "rvz:Z2025-000001:aa")

    def test_vazeny_median(self):
        self.assertEqual(api._vazeny_median([([1, 2, 3], 3), ([10], 1)]), 2)
        self.assertIsNone(api._vazeny_median([]))


if __name__ == "__main__":
    unittest.main()
