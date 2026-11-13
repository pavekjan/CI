import os
import subprocess
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import aktualizovat_db  # noqa: E402


class UrlOnlineDb(unittest.TestCase):
    def _url(self, origin):
        with mock.patch.object(subprocess, "run", return_value=mock.Mock(stdout=origin + "\n")):
            return aktualizovat_db.url_online_db()

    def test_https_i_ssh(self):
        cil = "https://raw.githubusercontent.com/pavekjan/CI/data/tenderscope.db.gz"
        self.assertEqual(self._url("https://github.com/pavekjan/CI.git"), cil)
        self.assertEqual(self._url("https://github.com/pavekjan/CI"), cil)
        self.assertEqual(self._url("git@github.com:pavekjan/CI.git"), cil)

    def test_neznamy_remote(self):
        self.assertIsNone(self._url(""))
        self.assertIsNone(self._url("https://example.com/x/y.git"))


if __name__ == "__main__":
    unittest.main()
