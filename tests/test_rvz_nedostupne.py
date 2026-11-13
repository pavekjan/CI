"""Kdyz server ISVZ neodpovida (napr. z cloudu), aktualizace nesmi zkouset vsechny mesice po 6 minutach."""
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from ts import db, scout  # noqa: E402
from ts.util import load_config  # noqa: E402


class Nedostupne(unittest.TestCase):
    def test_po_dvou_timeoutech_konec(self):
        volani = []

        def fetch(base, y, m, current=False):
            volani.append((y, m))
            raise RuntimeError("Nepodarilo se stahnout x: Connection to isvz.nipez.cz timed out. (connect timeout=120)")

        cfg = load_config()
        cfg["mesice"] = 12
        with tempfile.TemporaryDirectory() as d:
            con = db.connect(os.path.join(d, "t.db"))
            with mock.patch.object(scout.rvz, "fetch_month", fetch):
                stats = scout.scout_rvz(con, cfg)
            con.close()
        self.assertEqual(len(volani), 2)
        self.assertTrue(stats.get("nedostupne"))

    def test_chyba_dat_nepreskakuje(self):
        self.assertFalse(scout.je_nedostupny(RuntimeError("HTTP 500")))
        self.assertTrue(scout.je_nedostupny(RuntimeError("Max retries exceeded")))


if __name__ == "__main__":
    unittest.main()
