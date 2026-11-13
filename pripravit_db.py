"""Pripravi zmensenou kopii databaze pro online verzi (GitHub pres prohlizec bere soubory max. 25 MB).

    python pripravit_db.py              # vezme data/tenderscope.db -> predpripravena_db/tenderscope.db.gz
    python pripravit_db.py --limit 95   # pro vetev "data" (git push bere soubory az do 100 MB)

Puvodni databaze zustane beze zmeny. Kdyz je vysledek moc velky, skript postupne
vynecha Registr smluv a pak starsi zakazky, dokud se nevejde pod limit.
"""
import gzip
import os
import shutil
import sqlite3
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)
ZDROJ = os.path.join(ROOT, "data", "tenderscope.db")
CIL_DIR = os.path.join(ROOT, "predpripravena_db")
CIL = os.path.join(CIL_DIR, "tenderscope.db.gz")
TMP = os.path.join(ROOT, "data", "_online_kopie.db")
LIMIT_MB = 24  # GitHub pres prohlizec bere soubory max. 25 MB (git push az 100 MB, viz --limit)


def gz_velikost(path):
    with open(path, "rb") as f, gzip.open(CIL, "wb", compresslevel=9) as g:
        shutil.copyfileobj(f, g)
    return os.path.getsize(CIL) / 1e6


def smaz_stare(con, mesicu):
    con.execute("DELETE FROM zakazky WHERE COALESCE(datum_zahajeni, lhuta_nabidek, '') < date('now', ?)", (f"-{mesicu} months",))
    for t in ("vitezove", "ucastnici"):
        # bezpecnost: t je konstanta z kodu, ne vstup (vedome potlaceni nalezu banditu, viz SECURITY.md)
        con.execute(f"DELETE FROM {t} WHERE zakazka_id NOT IN (SELECT id FROM zakazky)")  # nosec B608
    con.execute("DELETE FROM priznaky WHERE objekt_typ='zakazka' AND objekt_id NOT IN (SELECT id FROM zakazky)")


def main():
    global LIMIT_MB
    if "--limit" in sys.argv:
        LIMIT_MB = max(1, min(95, int(sys.argv[sys.argv.index("--limit") + 1])))
    if not os.path.exists(ZDROJ):
        print("Nenasel jsem data/tenderscope.db. Nejdriv v aplikaci spustte aktualizaci dat.")
        return 1
    os.makedirs(CIL_DIR, exist_ok=True)
    if os.path.exists(TMP):
        os.remove(TMP)
    print("Kopiruji databazi...")
    src = sqlite3.connect(ZDROJ)
    src.execute("VACUUM INTO ?", (TMP,))
    src.close()
    con = sqlite3.connect(TMP)
    con.execute("DELETE FROM zpravy")
    # Co se z kopie vynecha, to se v ni oznaci jako nezpracovane, aby ho dalsi aktualizace (GitHub Actions
    # zacina z teto kopie) zase doplnila a nic se tise neztratilo.
    def bez_detailu_smluv():
        con.execute("DELETE FROM smlouvy_strany")
        con.execute("DELETE FROM smlouvy")
        con.execute("UPDATE soubory SET podpis='s:' || substr(podpis, 3) WHERE klic LIKE 'rs2:%' AND podpis LIKE 'd:%'")

    def souhrn_jen(mesicu):
        con.execute("DELETE FROM smlouvy_souhrn WHERE mesic < strftime('%Y-%m', 'now', ?)", (f"-{mesicu} months",))
        con.execute("DELETE FROM soubory WHERE klic LIKE 'rs2:%' AND substr(klic, 5, 4) || '-' || substr(klic, 10, 2) < "
                    "strftime('%Y-%m', 'now', ?)", (f"-{mesicu} months",))
        con.execute("DELETE FROM smlouvy_odberatele WHERE dump NOT IN (SELECT substr(klic, 5) FROM soubory WHERE klic LIKE 'rs2:%')")

    def zakazky_jen(mesicu):
        smaz_stare(con, mesicu)
        con.execute("DELETE FROM soubory WHERE klic LIKE 'rvz:%'")

    kroky = [("bez detailu Registru smluv (souhrn zustava)", bez_detailu_smluv),
             ("souhrn Registru smluv jen za 24 mesicu", lambda: souhrn_jen(24))]
    kroky += [(f"jen zakazky za poslednich {m} mesicu", (lambda m=m: zakazky_jen(m))) for m in (12, 6, 3)]
    popis = "cela databaze"
    while True:
        con.commit()
        con.execute("VACUUM")
        mb = gz_velikost(TMP)
        print(f"  {popis}: {mb:.1f} MB (zabaleno)")
        if mb <= LIMIT_MB or not kroky:
            break
        popis, krok = kroky.pop(0)
        krok()
        if popis.startswith("jen"):
            from ts import api
            api.rebuild_index(con)
    con.close()
    os.remove(TMP)
    if mb > LIMIT_MB:
        os.remove(CIL)
        print(f"Ani zmensena databaze se nevesla do {LIMIT_MB} MB. Online verze si data stahne sama po startu.")
        return 1
    print(f"\nHotovo: predpripravena_db/tenderscope.db.gz ({mb:.1f} MB, {popis}).")
    print("Nahrajte tento soubor na GitHub spolu s aplikaci (slozka predpripravena_db).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
