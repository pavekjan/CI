"""v18: velka databaze se do vetve data nahrava po castech (GitHub bere soubory max. 100 MB)."""
import gzip
import os
import sqlite3
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import pripravit_db  # noqa: E402
import server  # noqa: E402


def _db_gz(d):
    db = os.path.join(d, "x.db")
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE zakazky (id TEXT, nazev TEXT)")
    con.executemany("INSERT INTO zakazky VALUES (?, ?)", [(str(i), os.urandom(40).hex()) for i in range(3000)])
    con.commit()
    con.close()
    gz = os.path.join(d, "tenderscope.db.gz")
    with open(db, "rb") as f, gzip.open(gz, "wb") as g:
        g.write(f.read())
    return gz


class Odpoved:
    def __init__(self, data, kod=200):
        self.data, self.status_code = data, kod

    def iter_content(self, n):
        for i in range(0, len(self.data), n):
            yield self.data[i:i + n]

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class Casti(unittest.TestCase):
    def test_rozdel_a_stahni(self):
        d = tempfile.mkdtemp()
        gz = _db_gz(d)
        with open(gz, "rb") as f:
            cele = f.read()
        n = pripravit_db.rozdel(gz, len(cele) / 3.5 / 1e6)
        self.assertEqual(n, 4)
        soubory = {"https://raw.githubusercontent.com/a/b/data/tenderscope.db.gz": open(gz, "rb").read()}
        for i in range(2, n + 1):
            soubory[f"https://raw.githubusercontent.com/a/b/data/tenderscope.db.gz.{i}"] = open(f"{gz}.{i}", "rb").read()
        self.assertEqual(b"".join(soubory.values()), cele)
        get = lambda url, **k: Odpoved(soubory[url]) if url in soubory else Odpoved(b"", 404)  # noqa: E731
        cil = os.path.join(d, "stazena.db")
        with mock.patch("requests.get", side_effect=get):
            self.assertTrue(server.stahni_databazi("https://raw.githubusercontent.com/a/b/data/tenderscope.db.gz", cil))
        self.assertEqual(sqlite3.connect(cil).execute("SELECT COUNT(*) FROM zakazky").fetchone()[0], 3000)

    def test_jedna_cast_jako_drive(self):
        d = tempfile.mkdtemp()
        gz = _db_gz(d)
        self.assertEqual(pripravit_db.rozdel(gz, 95), 1)
        self.assertFalse(os.path.exists(gz + ".2"))


if __name__ == "__main__":
    unittest.main()
