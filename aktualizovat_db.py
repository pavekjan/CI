"""Aktualizace dat bez spusteni webu (pro aktualizovat_online.bat a GitHub Actions).

    python aktualizovat_db.py            # zakazky za 12 mesicu, Registr smluv: 36 mesicu souhrn + 3 mesice detail
                                         # (poprve to trva dlouho, dalsi behy jen doplni nove mesice)
    python aktualizovat_db.py --rychle   # jen poslednich par mesicu, bez Registru smluv
    python aktualizovat_db.py --online-db auto --jen-zakazky
                                         # stahne aktualni online databazi (vetev "data" na GitHubu) do
                                         # data/online.db a doplni do ni jen zakazky z ISVZ (ISVZ je dostupne
                                         # jen z ceskeho pocitace, Registr smluv doplnuje GitHub Actions)
    python aktualizovat_db.py --online-db auto --jen-registr
                                         # jen Registr smluv za 3 roky najednou (stahnout_registr_3roky.bat)
    python aktualizovat_db.py --online-db auto --vse-najednou
                                         # zakazky z ISVZ i Registr smluv za 3 roky v jednom behu
                                         # (finalni_aktualizace.bat, na noc)
    python aktualizovat_db.py --ai 400   # navic: zbytek zakazek bez segmentu zkusi rozradit AI (max. 400 na beh)

Uz zpracovane mesice se preskakuji a stazene soubory se berou z cache (data/cache), starsi data v databazi zustavaji.

Vraci chybovy kod, kdyz se nepodari stahnout zadne zakazky (napr. server ISVZ neodpovida).
"""
import os
import re
import subprocess  # nosec B404 - jen git remote get-url, pevne argumenty
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

import server  # noqa: E402
from ts.db import connect  # noqa: E402
from ts.util import load_config  # noqa: E402


def url_online_db():
    """Adresa databaze ve vetvi "data" podle git remote origin (https://github.com/<ucet>/<repo>)."""
    try:
        origin = subprocess.run(["git", "remote", "get-url", "origin"], cwd=ROOT, capture_output=True,  # nosec B603 B607
                                text=True, timeout=20).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        origin = ""
    m = re.search(r"github\.com[:/]([\w.-]+)/([\w.-]+?)(?:\.git)?/?$", origin)
    if not m:
        return None
    return f"https://raw.githubusercontent.com/{m.group(1)}/{m.group(2)}/data/tenderscope.db.gz"


def _pokrok(path):
    """Kolik mesicu Registru smluv a zakazek uz databaze obsahuje (podle tabulky soubory)."""
    import sqlite3
    try:
        con = sqlite3.connect(path)
        n = con.execute("SELECT COUNT(*) FROM soubory WHERE klic LIKE 'rs3:%' OR klic LIKE 'rvz:%'").fetchone()[0]
        con.close()
        return n
    except sqlite3.Error:
        return -1


def main():
    rezim = ("rychle" if "--rychle" in sys.argv else "plny" if "--plny" in sys.argv
             else "finalni" if "--vse-najednou" in sys.argv
             else "zakazky" if "--jen-zakazky" in sys.argv else "registr" if "--jen-registr" in sys.argv else "denni")
    server.STATE["cfg"] = load_config()
    if "--online-db" in sys.argv:
        # Pracuje nad aktualni online databazi (co do ni nahral GitHub Actions), ne nad data/tenderscope.db,
        # aby se pri nahrani nic z online verze neprepsalo starsimi daty.
        i = sys.argv.index("--online-db")
        url = sys.argv[i + 1] if len(sys.argv) > i + 1 and not sys.argv[i + 1].startswith("--") else "auto"
        if url == "auto":
            url = url_online_db()
        if not url:
            print("Nezjistil jsem adresu repozitare (git remote origin). Pouzijte --online-db https://...")
            return 1
        server.STATE["db"] = os.path.join(ROOT, "data", "online.db")
        os.makedirs(os.path.dirname(server.STATE["db"]), exist_ok=True)
        cil = server.STATE["db"]
        novy = cil + ".novy"
        if server.stahni_databazi(url, novy):
            if os.path.exists(cil) and _pokrok(cil) > _pokrok(novy):
                # predchozi beh na tomto pocitaci se nedokoncil (nebo se nenahral) -> pokracovat v nem
                print("Mistni data/online.db obsahuje vic zpracovanych mesicu nez online verze -> pokracuji v ni.")
                os.remove(novy)
            else:
                os.replace(novy, cil)
        if not os.path.exists(cil):
            lokalni = os.path.join(ROOT, "data", "tenderscope.db")
            if os.path.exists(lokalni):  # prvni beh bez vetve data: zacit z mistni databaze
                import shutil
                shutil.copyfile(lokalni, server.STATE["db"])
    if "--ci" in sys.argv:  # GitHub Actions: malo mista na disku a casovy limit -> historie po castech
        # ISVZ je z GitHubu blokovane -> zakazky jen z vaseho pocitace (aktualizovat_online.bat)
        server.STATE["cfg"].update({"mazat_stazene": True, "smlouvy_max_novych": 8, "rvz_preskocit": True})
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
    if server.JOB["chyba"] or (n == 0 and rezim != "registr"):
        print("Aktualizace se nepovedla:", server.JOB["chyba"] or "zadne zakazky")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
