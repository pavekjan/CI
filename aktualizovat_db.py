"""Aktualizace dat bez spusteni webu (pro aktualizovat_online.bat a GitHub Actions).

    python aktualizovat_db.py            # denni: posledni 3 mesice zakazek + aktualni mesic Registru smluv
    python aktualizovat_db.py --plny     # plna: zakazky za 12 mesicu + 3 mesice Registru smluv
    python aktualizovat_db.py --rychle   # jen poslednich par mesicu, bez Registru smluv

Uz zpracovane mesice se preskakuji a stazene soubory se berou z cache (data/cache), starsi data v databazi zustavaji.

Vraci chybovy kod, kdyz se nepodari stahnout zadne zakazky (napr. server ISVZ neodpovida).
"""
import os
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

import server  # noqa: E402
from ts.db import connect  # noqa: E402
from ts.util import load_config  # noqa: E402


def main():
    rezim = "plny" if "--plny" in sys.argv else "rychle" if "--rychle" in sys.argv else "denni"
    server.STATE["cfg"] = load_config()
    server.run_update(rezim)
    con = connect(server.STATE["db"])
    n = con.execute("SELECT COUNT(*) FROM zakazky").fetchone()[0]
    con.close()
    print(f"Zakazek v databazi: {n}")
    if server.JOB["chyba"] or n == 0:
        print("Aktualizace se nepovedla:", server.JOB["chyba"] or "zadne zakazky")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
