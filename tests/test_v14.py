"""v14: zakazky v DNS se neprepisuji (zmizela vyhra Alzy), dopocet ICO podle nazvu, bezpecny prepocet,
skore konkurenceschopnosti i z Registru smluv a s malym vzorkem."""
import json
import os
import sys
import tempfile
import unittest
from datetime import date
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from ts import api, db, extractor, scout  # noqa: E402
from ts.util import load_config  # noqa: E402


def _rec(nazev, vitez_ico, vitez):
    return {"EvidencniCisloVZnaVVZ": "Z2025-056221", "NazevVZ": nazev, "ZadavatelICO": "00006947",
            "Dodavatele": [{"DodavatelICO": vitez_ico, "DodavatelNazev": vitez, "CenaBezDPH": 7320}]}


class ZakazkyVDNS(unittest.TestCase):
    def test_dns7_a_dns8_jsou_dve_zakazky(self):
        z7, v7, _ = extractor.extract(_rec("DNS 7 - Elektronické a IT vybavení kanceláří", "29385920", "Nextis Services s.r.o."))
        z8, v8, _ = extractor.extract(_rec("DNS 8 - Elektronické a IT vybavení kanceláří", "27082440", "Alza.cz a.s."))
        self.assertNotEqual(z7["id"], z8["id"])
        self.assertTrue(z8["id"].startswith("rvz:Z2025-056221:"))
        self.assertEqual(z8["vvz_cislo"], "Z2025-056221")
        con = db.connect(os.path.join(tempfile.mkdtemp(), "t.db"))
        scout._save_zakazka(con, z8, v8, [])
        scout._save_zakazka(con, z7, v7, [])
        self.assertEqual(con.execute("SELECT COUNT(*) FROM vitezove WHERE dodavatel_ico='27082440'").fetchone()[0], 1)

    def test_stejna_zakazka_stejne_id_a_vitezove_se_scitaji(self):
        a, va, _ = extractor.extract(_rec("Nákup notebooků", "26165031", "Microshop,s.r.o."))
        b, vb, _ = extractor.extract(_rec("Nákup  notebooků", "27082440", "Alza.cz a.s."))   # cast 2, jiny vitez
        self.assertEqual(a["id"], b["id"])
        con = db.connect(os.path.join(tempfile.mkdtemp(), "t.db"))
        scout._save_zakazka(con, a, va, [])
        scout._save_zakazka(con, b, vb, [])
        self.assertEqual(con.execute("SELECT COUNT(*) FROM vitezove").fetchone()[0], 2)

    def test_nuts_neni_id(self):
        z, _, _ = extractor.extract({"KodNUTS": "CZ052", "NazevVZ": "Lesní cesta", "Kod": "513238"})
        self.assertFalse(z["id"].startswith("rvz:CZ"))


class BezpecnyPrepocet(unittest.TestCase):
    def test_nova_verze_bez_isvz_nic_nesmaze(self):
        con = db.connect(os.path.join(tempfile.mkdtemp(), "t.db"))
        con.execute("INSERT INTO zakazky (id, nazev) VALUES ('rvz:x', 'Stará data')")
        con.execute("INSERT INTO soubory VALUES ('extractor_verze', '2')")
        con.commit()
        cfg = load_config()
        cfg["mesice"] = 3

        def fetch(*a, **k):
            raise RuntimeError("Connection to isvz.nipez.cz timed out")
        with mock.patch.object(scout.rvz, "fetch_month", fetch):
            scout.scout_rvz(con, cfg)
        self.assertEqual(con.execute("SELECT COUNT(*) FROM zakazky").fetchone()[0], 1)   # GitHub/Render: data zustanou
        self.assertEqual(con.execute("SELECT podpis FROM soubory WHERE klic='extractor_verze'").fetchone()[0], "2")

    def test_jen_registr_nestahuje_zakazky(self):
        con = db.connect(os.path.join(tempfile.mkdtemp(), "t.db"))
        with mock.patch.object(scout.rvz, "fetch_month", side_effect=AssertionError):
            self.assertTrue(scout.scout_rvz(con, dict(load_config(), rvz_preskocit=True))["preskoceno"])


class IcoPodleNazvu(unittest.TestCase):
    def test_doplneni(self):
        con = db.connect(os.path.join(tempfile.mkdtemp(), "t.db"))
        con.executemany("INSERT INTO ucastnici (zakazka_id, dodavatel_ico, dodavatel_nazev) VALUES (?,?,?)", [
            ("a", "27082440", "Alza.cz a.s."), ("b", None, "ALZA.CZ a.s."), ("c", None, "Neznámá s.r.o."),
            ("d", "1", "Dvojí s.r.o."), ("e", "2", "Dvojí s.r.o."), ("f", None, "Dvojí s.r.o.")])
        self.assertEqual(api.doplnit_ico_podle_nazvu(con), 1)
        self.assertEqual(con.execute("SELECT dodavatel_ico FROM ucastnici WHERE zakazka_id='b'").fetchone()[0], "27082440")
        self.assertIsNone(con.execute("SELECT dodavatel_ico FROM ucastnici WHERE zakazka_id='f'").fetchone()[0])  # nejednoznacne


class SkoreSRegistrem(unittest.TestCase):
    def test_firma_bez_vyher_ale_se_smlouvami(self):
        """Alza: 0 z 3 soutezi, ale 90 smluv u 68 zadavatelu -> nesmi mit 0 a ma priznak malo dat."""
        con = db.connect(os.path.join(tempfile.mkdtemp(), "t.db"))
        for i in range(3):
            con.execute("INSERT INTO zakazky (id, nazev, cpv_hlavni, datum_zahajeni) VALUES (?,?,?,?)",
                        (f"z{i}", f"Notebooky {i}", "30213100", "2026-05-01"))
            con.execute("INSERT INTO ucastnici (zakazka_id, dodavatel_ico) VALUES (?, '27082440')", (f"z{i}",))
            con.execute("INSERT INTO ucastnici (zakazka_id, dodavatel_ico) VALUES (?, '26165031')", (f"z{i}",))
            con.execute("INSERT INTO vitezove (zakazka_id, dodavatel_ico, cena_bez_dph) VALUES (?, '26165031', 1e5)", (f"z{i}",))
        con.execute("INSERT INTO smlouvy_souhrn VALUES ('27082440', '2026-10', 'd1', 90, 9e6)")
        for k in range(68):
            con.execute("INSERT INTO smlouvy_odberatele VALUES ('27082440', ?, 'd1', 1, ?)", (f"{k:08d}", 9e6 / 68))
        con.execute("INSERT INTO smlouvy_souhrn VALUES ('11111111', '2026-10', 'd1', 2, 1e5)")
        con.commit()
        api.rebuild_index(con)
        p = api.profil(con, "27082440", load_config(), today=date(2026, 11, 13), online=False)
        sk = {s["klic"]: s for s in p["skore"]["slozky"]}
        self.assertGreater(sk["uspesnost"]["skore"], 20)            # 0/3 je pritazeno k trhu, ne 0
        self.assertTrue(sk["uspesnost"]["malo_dat"])
        self.assertIn("Registr smluv", sk["pozice"]["vysvetleni"])
        self.assertGreater(sk["klienti"]["skore"], 60)              # 68 zakazniku
        self.assertGreater(p["skore"]["celkem"], 40)
        self.assertTrue(p["skore"]["malo_dat"])
        json.dumps(p, default=str)


if __name__ == "__main__":
    unittest.main()
