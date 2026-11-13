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
SOUBOR = os.path.join(ROOT, "predpripravena_db", "tenderscope.db.gz")


def git(*args, cwd):
    subprocess.run(["git", *args], cwd=cwd, check=True)  # nosec B603 B607 - pevny prikaz git, zadny shell


def main():
    if not os.path.exists(SOUBOR):
        print("Chybi predpripravena_db/tenderscope.db.gz. Nejdriv spustte pripravit_db.py.")
        return 1
    if "--remote" in sys.argv:
        remote = sys.argv[sys.argv.index("--remote") + 1]
    else:
        remote = subprocess.run(["git", "remote", "get-url", "origin"], cwd=ROOT, check=True,  # nosec B603 B607
                                capture_output=True, text=True).stdout.strip()
    tmp = tempfile.mkdtemp(prefix="ts-data-")
    try:
        shutil.copy(SOUBOR, os.path.join(tmp, "tenderscope.db.gz"))
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
