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

    def test_vazeny_median(self):
        self.assertEqual(api._vazeny_median([([1, 2, 3], 3), ([10], 1)]), 2)
        self.assertIsNone(api._vazeny_median([]))


if __name__ == "__main__":
    unittest.main()
