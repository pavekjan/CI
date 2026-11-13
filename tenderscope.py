"""TenderScope - multiagentni system pro competitive intelligence ve verejnych zakazkach.

Pouziti (Windows: misto python3 pis python):
    python tenderscope.py run                     # stahne vse a vytvori brief (obor z config.json)
    python tenderscope.py run --obor stavebnictvi --mesice 12
    python tenderscope.py run --rychle            # rychly beh: 3 mesice, bez Registru smluv
    python tenderscope.py run --bez-stahovani     # jen prepocita analyzu z jiz stazenych dat
    python tenderscope.py run --tydenni --ano     # tydenni brief, bez dotazu na schvaleni
    python tenderscope.py firma 27082440          # profil firmy z ARES
    python tenderscope.py inspect                 # ukaze skutecnou strukturu JSON z RVZ (ladeni)
    python tenderscope.py demo                    # ukazkovy beh na umelych datech, bez internetu
"""
import argparse
import json
import os
import sys
import webbrowser

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from ts import extractor, orchestrator  # noqa: E402
from ts.sources import rvz  # noqa: E402
from ts.sources.other import ares_firma  # noqa: E402
from ts.util import load_config, log, months_back  # noqa: E402


def cmd_run(a):
    cfg = load_config(a.config)
    if a.obor:
        cfg["obor"] = a.obor
    if a.rychle:
        # rychly rezim: posledni 3 mesice, bez velkych dumpu Registru smluv, mene dotazu na ARES/zpravy
        cfg.update({"mesice": 3, "smlouvy_mesice": 0, "ares_max_firem": 20, "zpravy_max_konkurentu": 3})
    if a.mesice:
        cfg["mesice"] = a.mesice
    if a.smlouvy_mesice is not None:
        cfg["smlouvy_mesice"] = a.smlouvy_mesice
    if a.ico:
        cfg["nase_ico"] = a.ico
    sources = set(a.zdroje.split(",")) if a.zdroje else None
    res = orchestrator.run(cfg, skip_download=a.bez_stahovani, auto_approve=a.ano,
                           typ="týdenní" if a.tydenni else "denní", sources=sources)
    if res and not a.neotvirat:
        webbrowser.open("file://" + os.path.abspath(res["brief_html"]))


def cmd_firma(a):
    cfg = load_config(a.config)
    f = ares_firma(cfg["zdroje"]["ares_base"], a.ico.zfill(8))
    print(json.dumps(f, ensure_ascii=False, indent=2) if f else "Firma v ARES nenalezena.")


def cmd_inspect(a):
    cfg = load_config(a.config)
    for y, m in reversed(months_back(4)):
        path = rvz.fetch_month(cfg["zdroje"]["rvz_base"], y, m)
        if path:
            rec = rvz.first_record(path)
            print(f"\nPrvni zaznam ze souboru {os.path.basename(path)} - cesty klicu:\n")
            print("\n".join(extractor.describe_keys(rec)))
            zak, vit, uc = extractor.extract(rec)
            print("\nCo z nej Extractor vytahl:")
            print(json.dumps({"zakazka": zak, "vitezove": vit, "ucastnici": uc}, ensure_ascii=False, indent=2))
            return
    print("Nenasel jsem zadny mesicni soubor RVZ.")


def cmd_demo(a):
    import demo
    demo.main(open_browser=not a.neotvirat)


def main():
    p = argparse.ArgumentParser(description="TenderScope - CI pro verejne zakazky")
    p.add_argument("--config", default=None, help="cesta ke config.json")
    sub = p.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("run", help="spusti cely workflow agentu")
    r.add_argument("--obor", choices=["it", "stavebnictvi"])
    r.add_argument("--rychle", action="store_true", help="rychly beh: 3 mesice, bez Registru smluv (par minut)")
    r.add_argument("--mesice", type=int, help="kolik mesicu zpet (vychozi 12)")
    r.add_argument("--smlouvy-mesice", type=int, dest="smlouvy_mesice", help="kolik mesicu Registru smluv (dumpy jsou velke)")
    r.add_argument("--ico", help="IČO vasi firmy pro KIQ 5")
    r.add_argument("--zdroje", help="jen vybrane zdroje: rvz,hlidac,smlouvy,ares,zpravy")
    r.add_argument("--bez-stahovani", action="store_true", dest="bez_stahovani")
    r.add_argument("--ano", action="store_true", help="automaticky schvalit brief")
    r.add_argument("--tydenni", action="store_true")
    r.add_argument("--neotvirat", action="store_true", help="neotvirat brief v prohlizeci")
    r.set_defaults(fn=cmd_run)

    f = sub.add_parser("firma", help="profil firmy z ARES")
    f.add_argument("ico")
    f.set_defaults(fn=cmd_firma)

    i = sub.add_parser("inspect", help="ukaze strukturu open dat RVZ")
    i.set_defaults(fn=cmd_inspect)

    d = sub.add_parser("demo", help="ukazkovy beh bez internetu")
    d.add_argument("--neotvirat", action="store_true")
    d.set_defaults(fn=cmd_demo)

    a = p.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()
