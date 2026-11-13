"""Aktualizace dat bez spusteni webu (pro aktualizovat_online.bat a GitHub Actions).

    python aktualizovat_db.py            # zakazky za 12 mesicu, Registr smluv: 36 mesicu souhrn + 3 mesice detail
                                         # (poprve to trva dlouho, dalsi behy jen doplni nove mesice)
    python aktualizovat_db.py --rychle   # jen poslednich par mesicu, bez Registru smluv
    python aktualizovat_db.py --ai 400   # navic: zbytek zakazek bez segmentu zkusi rozradit AI (max. 400 na beh)

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
    rezim = "rychle" if "--rychle" in sys.argv else "plny" if "--plny" in sys.argv else "denni"
    server.STATE["cfg"] = load_config()
    if "--z-url" in sys.argv and not os.path.exists(server.STATE["db"]):
        # GitHub Actions: zacit z posledni nahrane databaze -> zpracovavaji se jen nove mesice
        os.makedirs(os.path.dirname(server.STATE["db"]), exist_ok=True)
        server.stahni_databazi(sys.argv[sys.argv.index("--z-url") + 1], server.STATE["db"])
    if "--ai" in sys.argv:
        i = sys.argv.index("--ai")
        server.STATE["ai_segmenty"] = int(sys.argv[i + 1]) if len(sys.argv) > i + 1 and sys.argv[i + 1].isdigit() else 400
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
