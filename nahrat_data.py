"""Nahraje predpripravena_db/tenderscope.db.gz do vetve "data" na GitHubu.

Vetev "data" obsahuje vzdy jen jeden soubor a pri kazdem nahrani se prepise (historie neroste).
Online verze si odtud databazi stahne pri startu (promenna TS_DB_URL v render.yaml).

    python nahrat_data.py                   # pouzije adresu repozitare z "git remote" (vase prihlaseni do GitHubu)
    python nahrat_data.py --remote URL      # jina adresa (pouziva GitHub Actions)
"""
import os
import shutil
import subprocess  # nosec B404 - spousti jen git s pevnymi argumenty
import sys
import tempfile

ROOT = os.path.dirname(os.path.abspath(__file__))
SOUBOR = os.path.join(ROOT, "data", "nahrani", "tenderscope.db.gz")  # pripravit_db.py --limit (casti .2, .3 ...)
STARY = os.path.join(ROOT, "predpripravena_db", "tenderscope.db.gz")


def git(*args, cwd):
    subprocess.run(["git", *args], cwd=cwd, check=True)  # nosec B603 B607 - pevny prikaz git, zadny shell


def main():
    soubor = SOUBOR if os.path.exists(SOUBOR) else STARY
    if not os.path.exists(soubor):
        print("Chybi data/nahrani/tenderscope.db.gz. Nejdriv spustte pripravit_db.py --limit 95.")
        return 1
    casti = [soubor] + [f"{soubor}.{i}" for i in range(2, 21) if os.path.exists(f"{soubor}.{i}")]
    if "--remote" in sys.argv:
        remote = sys.argv[sys.argv.index("--remote") + 1]
    else:
        remote = subprocess.run(["git", "remote", "get-url", "origin"], cwd=ROOT, check=True,  # nosec B603 B607
                                capture_output=True, text=True).stdout.strip()
    tmp = tempfile.mkdtemp(prefix="ts-data-")
    try:
        for i, c in enumerate(casti, 1):
            shutil.copy(c, os.path.join(tmp, "tenderscope.db.gz" + ("" if i == 1 else f".{i}")))
        print(f"Nahravam {len(casti)} {'soubor' if len(casti) == 1 else 'soubory'} "
              f"({sum(os.path.getsize(c) for c in casti) / 1e6:.0f} MB) ...")
        with open(os.path.join(tmp, "README.md"), "w", encoding="utf-8") as f:
            f.write("Automaticky nahravana databaze TenderScope (verejna data statu). Vetev se pri kazdem nahrani prepise.\n")
        git("init", "-q", cwd=tmp)
        git("checkout", "-q", "-b", "data", cwd=tmp)
        git("add", "-A", cwd=tmp)
        git("-c", "user.name=TenderScope", "-c", "user.email=tenderscope@users.noreply.github.com",
            "commit", "-q", "-m", "Aktualni databaze", cwd=tmp)
        git("push", "-q", "--force", remote, "data", cwd=tmp)
        print("Hotovo: databaze je na GitHubu ve vetvi 'data'. Online verze ji nacte pri pristim startu.")
        return 0
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
