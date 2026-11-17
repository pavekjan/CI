"""v17: stahovani velkych souboru navaze po preruseni spojeni (usnuti pocitace, vypadek site)."""
import os
import sys
import tempfile
import unittest
from unittest import mock

import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from ts import util  # noqa: E402

DATA = bytes(range(256)) * 20000  # ~5 MB


class Odpoved:
    def __init__(self, od, prerusit_po=None, umi_range=True):
        self.status_code = 206 if od and umi_range else 200
        self.headers = {"Content-Length": str(len(DATA) - (od if umi_range else 0))}
        self.od, self.prerusit_po = (od if umi_range else 0), prerusit_po

    def iter_content(self, chunk_size):
        pos, poslano = self.od, 0
        while pos < len(DATA):
            if self.prerusit_po is not None and poslano >= self.prerusit_po:
                raise requests.exceptions.ChunkedEncodingError("Connection broken")
            kus = DATA[pos:pos + chunk_size]
            pos += len(kus)
            poslano += len(kus)
            yield kus


class Navazani(unittest.TestCase):
    def _stahni(self, umi_range):
        volani = []

        def get(url, headers=None, **k):
            od = int(headers["Range"][6:-1]) if headers else 0
            volani.append(od)
            return Odpoved(od, prerusit_po=(2 << 20) if len(volani) == 1 else None, umi_range=umi_range)
        dest = os.path.join(tempfile.mkdtemp(), "x.xml")
        with mock.patch.object(util, "http_get", side_effect=get), mock.patch.object(util.time, "sleep"):
            util.download("https://x/x.xml", dest)
        with open(dest, "rb") as f:
            self.assertEqual(f.read(), DATA)
        self.assertFalse(os.path.exists(dest + ".part"))
        return volani

    def test_navaze_od_mista_preruseni(self):
        v = self._stahni(True)
        self.assertEqual(v[0], 0)
        self.assertGreater(v[1], 0)

    def test_server_bez_range_stahne_znovu(self):
        self._stahni(False)

    def test_nedostupny_server_bez_cekani(self):
        with mock.patch.object(util, "http_get", side_effect=RuntimeError("timed out")), \
                mock.patch.object(util.time, "sleep") as sl:
            with self.assertRaises(RuntimeError):
                util.download("https://x/y.zip", os.path.join(tempfile.mkdtemp(), "y.zip"))
        sl.assert_not_called()


if __name__ == "__main__":
    unittest.main()
