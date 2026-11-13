"""Stazeni aktualni databaze pro online verzi (TS_DB_URL) a nahrani do vetve data."""
import gzip
import http.server
import os
import shutil
import sqlite3
import subprocess  # nosec B404
import sys
import tempfile
import threading
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import server  # noqa: E402


def _gz_db(path, zakazek=3):
    d = path + ".db"
    con = sqlite3.connect(d)
    con.execute("CREATE TABLE zakazky (id TEXT)")
    con.executemany("INSERT INTO zakazky VALUES (?)", [(str(i),) for i in range(zakazek)])
    con.commit()
    con.close()
    with open(d, "rb") as f, gzip.open(path, "wb") as g:
        g.write(f.read())
    os.remove(d)


class StazeniDB(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        _gz_db(os.path.join(self.d, "tenderscope.db.gz"))
        with open(os.path.join(self.d, "spatne.db.gz"), "wb") as f:
            f.write(gzip.compress(b"tohle neni databaze"))
        d = self.d

        class H(http.server.SimpleHTTPRequestHandler):
            def __init__(self, *a, **k):
                super().__init__(*a, directory=d, **k)

            def log_message(self, *a):
                pass

        self.srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.base = f"http://127.0.0.1:{self.srv.server_address[1]}/"
        self.cil = os.path.join(self.d, "out.db")

    def tearDown(self):
        self.srv.shutdown()
        shutil.rmtree(self.d, ignore_errors=True)

    def test_ssrf_lokalni_adresa_odmitnuta(self):
        self.assertFalse(server.stahni_databazi(self.base + "tenderscope.db.gz", self.cil))
        self.assertFalse(os.path.exists(self.cil))

    def test_stazeni_a_kontrola(self):
        with mock.patch.object(server.bezpecnost, "over_api_url", lambda u, v: u):
            self.assertTrue(server.stahni_databazi(self.base + "tenderscope.db.gz", self.cil))
            con = sqlite3.connect(self.cil)
            self.assertEqual(con.execute("SELECT COUNT(*) FROM zakazky").fetchone()[0], 3)
            con.close()
            os.remove(self.cil)
            self.assertFalse(server.stahni_databazi(self.base + "spatne.db.gz", self.cil))
            self.assertFalse(server.stahni_databazi(self.base + "neexistuje.gz", self.cil))
            self.assertFalse(server.stahni_databazi(self.base + "tenderscope.db.gz", self.cil, max_bajtu=10))
        self.assertFalse(os.path.exists(self.cil))
        self.assertEqual([f for f in os.listdir(self.d) if ".dl" in f], [])


@unittest.skipUnless(shutil.which("git"), "git neni nainstalovany")
class VetevData(unittest.TestCase):
    def test_nahrani_prepise_vetev(self):
        import nahrat_data
        d = tempfile.mkdtemp()
        try:
            remote = os.path.join(d, "remote.git")
            subprocess.run(["git", "init", "-q", "--bare", remote], check=True)  # nosec
            gz = os.path.join(d, "x.gz")
            _gz_db(gz)
            with mock.patch.object(nahrat_data, "SOUBOR", gz), mock.patch.object(sys, "argv", ["x", "--remote", remote]):
                self.assertEqual(nahrat_data.main(), 0)
                self.assertEqual(nahrat_data.main(), 0)  # podruhe prepise, historie neroste
            log = subprocess.run(["git", "--git-dir", remote, "log", "--oneline", "data"], check=True,  # nosec
                                 capture_output=True, text=True).stdout.strip().splitlines()
            self.assertEqual(len(log), 1)
            soubory = subprocess.run(["git", "--git-dir", remote, "ls-tree", "--name-only", "data"], check=True,  # nosec
                                     capture_output=True, text=True).stdout.split()
            self.assertEqual(sorted(soubory), ["README.md", "tenderscope.db.gz"])
        finally:
            shutil.rmtree(d, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
