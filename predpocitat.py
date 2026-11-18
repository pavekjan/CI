"""Znovu spocita prehledy trhu v databazi (tabulka cache), aby je online verze jen nacetla.
Spousti se samo pri kazde aktualizaci (rebuild_index); rucne jen pro uz hotovou databazi:

    python predpocitat.py data/online.db
"""
import os
import sys
import time

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

from ts import api  # noqa: E402
from ts.db import connect  # noqa: E402


def main():
    cesta = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "data", "online.db")
    if not os.path.exists(cesta):
        print(f"Nenasel jsem {cesta}.")
        return 1
    t = time.time()
    con = connect(cesta)
    api.predpocitat(con)
    n = con.execute("SELECT COUNT(*) FROM cache").fetchone()[0]
    con.close()
    print(f"Hotovo: {n} predpocitanych prehledu ({time.time() - t:.0f} s).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
