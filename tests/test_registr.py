"""Registr smluv: souhrn za dlouhe obdobi, preskakovani hotovych mesicu, profil firmy."""
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from ts import api, db, scout  # noqa: E402
from ts.util import load_config  # noqa: E402


def _zaznam(i, zad, dod, hodnota, datum):
    return f"""<zaznam><identifikator><idSmlouvy>{i}</idSmlouvy><idVerze>{i}v</idVerze></identifikator>
<odkaz>https://smlouvy.gov.cz/smlouva/{i}</odkaz><platnyZaznam>1</platnyZaznam>
<smlouva><subjekt><ico>{zad}</ico><nazev>Nemocnice {zad}</nazev></subjekt>
<smluvniStrana><ico>{dod}</ico><nazev>Firma {dod}</nazev></smluvniStrana>
<predmet>Dodavka c. {i}</predmet><datumUzavreni>{datum}</datumUzavreni><hodnotaBezDph>{hodnota}</hodnotaBezDph></smlouva></zaznam>"""


class Registr(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.con = db.connect(os.path.join(self.d, "t.db"))
        self.cfg = load_config()
        self.cfg.update({"obor": "vse", "smlouvy_mesice": 1, "smlouvy_souhrn_mesice": 3})
        self.dumpy = []
        for k, (rok, mes) in enumerate([(2026, 8), (2026, 9), (2026, 10)]):
            p = os.path.join(self.d, f"d{k}.xml")
            with open(p, "w", encoding="utf-8") as f:
                f.write("<dump>" + "".join(_zaznam(f"{k}-{j}", "00064165", "27082440", 1000 * (j + 1), f"{rok}-{mes:02d}-1{j}")
                                         for j in range(3)) + "</dump>")
            self.dumpy.append({"rok": rok, "mesic": mes, "odkaz": p, "velikost": 1, "dokonceny": k < 2, "_cesta": p})
        self.stazeno = []

    def _beh(self):
        def fetch_dump(d):
            self.stazeno.append(d["mesic"])
            return d["_cesta"]
        with mock.patch.object(scout.smlouvy, "fetch_index", lambda base: [dict(x) for x in self.dumpy]), \
                mock.patch.object(scout.smlouvy, "fetch_dump", fetch_dump):
            return scout.scout_smlouvy(self.con, self.cfg)

    def test_souhrn_a_detail(self):
        st = self._beh()
        self.assertEqual(st["smluv"], 9)
        self.assertEqual(st["detail"], 3)  # cele smlouvy jen za posledni mesic
        rs = api.rs_firmy(self.con, "27082440", mesicu=600)
        self.assertEqual(rs["pocet"], 9)
        self.assertEqual(rs["objem"], 18000)
        self.assertEqual(rs["odberatele"][0]["nazev"], "Nemocnice 00064165")
        self.assertIsNone(api.rs_firmy(self.con, "00064165"))  # zadavatel neni dodavatel
        o = api.obdobi(self.con)
        self.assertEqual((o["rs_od"], o["rs_do"], o["rs_mesicu"]), ("2026-08", "2026-10", 3))

    def test_hotove_mesice_se_nestahuji_znovu(self):
        self._beh()
        self.stazeno.clear()
        self._beh()
        self.assertEqual(self.stazeno, [10])  # jen nedokonceny mesic
        self.assertEqual(api.rs_firmy(self.con, "27082440", mesicu=600)["pocet"], 9)  # nic se nezdvojilo

    def test_index_a_hledani(self):
        self._beh()
        api.rebuild_index(self.con)
        r = api.hledat(self.con, "firma 27082440")
        self.assertEqual(r[0]["ico"], "27082440")
        self.assertEqual(r[0]["smluv_rs"], 9)


    def test_graf(self):
        self._beh()
        self.con.execute("INSERT INTO zakazky (id, nazev, cpv_hlavni, zadavatel_ico, zadavatel_nazev, datum_zahajeni) VALUES ('z1','Notebooky','30213100','00064165','Nemocnice','2026-09-01')")
        self.con.execute("INSERT INTO vitezove (zakazka_id, dodavatel_ico, dodavatel_nazev, cena_bez_dph) VALUES ('z1','27082440','Alza.cz a.s.',1e6)")
        self.con.commit()
        api.rebuild_index(self.con)
        g = api.graf(self.con, "27082440", self.cfg)
        typy = {u["typ"] for u in g["uzly"]}
        self.assertTrue({"firma", "zadavatel", "zakazka", "obor", "zdroj"} <= typy)
        ids = {u["id"] for u in g["uzly"]}
        self.assertTrue(all(h["od"] in ids and h["do"] in ids for h in g["hrany"]))
        self.assertTrue(all(u["odkaz"] is None or u["odkaz"].startswith(("#/", "https://")) for u in g["uzly"]))


if __name__ == "__main__":
    unittest.main()
