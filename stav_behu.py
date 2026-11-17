"""Kam dosla posledni aktualizace: pocty v mistni databazi, posledni kroky a konec posledniho logu."""
import glob
import os
import sqlite3
import sys

Q_RVZ = "SELECT COUNT(*) FROM soubory WHERE klic LIKE 'rvz:%'"
Q_RS = "SELECT COUNT(*) FROM soubory WHERE klic LIKE 'rs3:%'"
ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)


def main():
    for jmeno in ("online.db", "tenderscope.db"):
        cesta = os.path.join(ROOT, "data", jmeno)
        if not os.path.exists(cesta):
            continue
        con = sqlite3.connect(cesta)
        one = lambda q: con.execute(q).fetchone()[0]  # noqa: E731
        print(f"== data/{jmeno} ({os.path.getsize(cesta) / 1e6:.0f} MB)")
        print(f"  zakazek: {one('SELECT COUNT(*) FROM zakazky')}")
        verze = con.execute("SELECT podpis FROM soubory WHERE klic='extractor_verze'").fetchone()
        print(f"  verze zpracovani zakazek: {verze[0] if verze else '-'} (aktualni je 4)")
        print(f"  hotovych mesicu zakazek: {one(Q_RVZ)}")
        print(f"  hotovych souboru Registru smluv: {one(Q_RS)}")
        print("  posledni kroky:")
        for r in con.execute("SELECT konec, krok, stav FROM behy ORDER BY id DESC LIMIT 6"):
            print(f"    {r[0]}  {r[1]}  {r[2]}")
        con.close()
    logy = sorted(glob.glob(os.path.join(ROOT, "data", "logy", "*.log")))
    if logy:
        print(f"== konec logu {os.path.basename(logy[-1])}")
        with open(logy[-1], encoding="utf-8", errors="replace") as f:
            for radek in f.readlines()[-15:]:
                print("  " + radek.rstrip()[:200])


if __name__ == "__main__":
    main()
