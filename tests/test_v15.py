"""v15: zakazky bez cisla ve Vestniku (jen profil / NEN) se uz nezahazuji; srovnani s Hlidacem statu."""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from ts import api, extractor  # noqa: E402

ALZA = {"ICO": "27082440", "Nazev": "Alza.cz a.s."}


class ZakazkyMimoVestnik(unittest.TestCase):
    def test_jen_identifikator_nipez(self):
        rec = {"EvidencniCisloVZnaVVZ": "", "IdentifikatorNIPEZ": "RVZ2600112233", "NazevVZ": "Notebooky pro školu",
               "Zadavatel": {"ICO": "00064581", "Nazev": "Praha"}, "Dodavatel": [ALZA]}
        z, vit, _ = extractor.extract(rec)
        self.assertTrue(z["id"].startswith("rvz:RVZ2600112233"))
        self.assertEqual(z["nipez_id"], "RVZ2600112233")
        self.assertEqual(vit[0]["dodavatel_ico"], "27082440")

    def test_jen_cislo_nen(self):
        rec = {"SystemoveCislo": "N006/26/V00015651", "NazevVZ": "Tonery", "Zadavatel": {"ICO": "00064581"}}
        z, _, _ = extractor.extract(rec)
        self.assertTrue(z["id"].startswith("rvz:N006/26/V00015651"))

    def test_bez_cisla_otisk_zadavatele_a_nazvu(self):
        rec = {"NazevVZ": "Dodávka monitorů", "Zadavatel": {"ICO": "00064581", "Nazev": "Praha"}}
        a, _, _ = extractor.extract(rec)
        b, _, _ = extractor.extract(dict(rec))
        self.assertIsNotNone(a["id"])
        self.assertEqual(a["id"], b["id"])                    # stabilni -> dalsi zaznamy teze zakazky se spoji

    def test_cislo_dodavatele_neni_cislo_zakazky(self):
        rec = {"Dodavatel": {"ICO": "27082440", "Poznamka": "RVZ2600000001"}}
        z, _, _ = extractor.extract(rec)
        self.assertIsNone(z["id"])                            # bez nazvu a zadavatele to zakazka neni


class HlidacSrovnani(unittest.TestCase):
    def test_bez_tokenu_jen_odkazy(self):
        h = api.hlidac_smlouvy({"zdroje": {"hlidac_base": "x"}}, "27082440")
        self.assertIsNone(h["zakazky"])
        self.assertIn("icododavatel%3A27082440", h["zakazky_url"])

    def test_s_tokenem_pocty(self):
        api._HLIDAC_CACHE.clear()
        odp = lambda url, **k: mock.Mock(status_code=200, json=lambda: {"Total": 357 if "verejne" in url else 7521})
        with mock.patch.object(api, "http_get", side_effect=odp):
            h = api.hlidac_smlouvy({"hlidac_token": "t", "zdroje": {"hlidac_base": "https://api/"}}, "27082440")
        self.assertEqual((h["pocet"], h["zakazky"]), (7521, 357))


if __name__ == "__main__":
    unittest.main()
