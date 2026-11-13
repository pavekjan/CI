"""ORCHESTRATOR - ridi workflow agentu a lidske schvaleni.

    Scout (RVZ/NEN/VVZ) -> Extractor (uvnitr Scoutu, zaznam po zaznamu)
      -> Scout (Hlidac statu, Registr smluv, ARES, zpravy)
      -> Verifier -> Analyst -> Briefer -> [schvaleni clovekem] -> finalni brief

Kazdy krok se loguje do tabulky `behy`; chyba jednoho zdroje nezastavi cely beh.
"""
import traceback
from datetime import datetime

from . import analyst, briefer, scout, verifier
from .db import connect
from .util import log

A = "Orchestrator"


def _step(con, name, fn, stats, *args):
    start = datetime.now().isoformat(timespec="seconds")
    cur = con.execute("INSERT INTO behy (zacatek, krok, stav) VALUES (?,?,?)", (start, name, "bezi"))
    rid = cur.lastrowid
    con.commit()
    log(A, f"-> {name}")
    try:
        res = fn(*args)
        stats[name] = res if not isinstance(res, dict) or len(str(res)) < 300 else "OK"
        con.execute("UPDATE behy SET konec=?, stav='ok', poznamka=? WHERE id=?",
                    (datetime.now().isoformat(timespec="seconds"), str(res)[:500], rid))
        con.commit()
        return res
    except Exception as e:
        log(A, f"!! {name} selhal: {e}")
        traceback.print_exc()
        stats[name] = f"CHYBA: {e}"
        con.execute("UPDATE behy SET konec=?, stav='chyba', poznamka=? WHERE id=?",
                    (datetime.now().isoformat(timespec="seconds"), str(e)[:500], rid))
        con.commit()
        return None


def run(cfg, *, skip_download=False, auto_approve=False, today=None, db_path=None, typ="denní", sources=None, suffix=""):
    con = connect(db_path)
    stats = {}
    sources = sources or {"rvz", "hlidac", "smlouvy", "ares", "zpravy"}
    log(A, f"start | obor: {cfg['obory'][cfg['obor']]['nazev']} | {cfg['mesice']} mesicu")

    if not skip_download:
        if "rvz" in sources:
            _step(con, "Scout+Extractor: RVZ/NEN/Věstník", scout.scout_rvz, stats, con, cfg, today)
        if "hlidac" in sources:
            _step(con, "Scout: Hlídač státu", scout.scout_hlidac, stats, con, cfg)
        if "smlouvy" in sources:
            _step(con, "Scout: Registr smluv", scout.scout_smlouvy, stats, con, cfg)
        if "ares" in sources:
            _step(con, "Scout: ARES", scout.scout_ares, stats, con, cfg)
        if "zpravy" in sources:
            _step(con, "Scout: zprávy RSS", scout.scout_zpravy, stats, con, cfg)
    else:
        log(A, "stahovani preskoceno (--bez-stahovani), pracuji s databazi")

    ver = _step(con, "Verifier", verifier.run, stats, con) or {}
    an = _step(con, "Analyst", analyst.run, stats, con, cfg, today)
    if an is None:
        log(A, "Analyza selhala, brief nevytvarim.")
        return None
    zpravy = [dict(r) for r in con.execute("SELECT * FROM zpravy ORDER BY datum DESC LIMIT 20")]
    md = briefer.build(an, ver, cfg, stats, zpravy, typ=typ)

    # ---- lidske schvaleni ----
    draft_md, draft_html = briefer.save(md, approved=False, suffix=suffix)
    approved = auto_approve or not cfg.get("schvaleni", True)
    if not approved:
        print("\n" + "=" * 70)
        print(f"NAVRH BRIEFU je pripraven ke kontrole:\n  {draft_html}")
        top = an["prilezitosti"][:5]
        for p in top:
            print(f"  [{p['doporuceni']:<7}] {p['skore']:>3}  {p['nazev']}")
        print("=" * 70)
        try:
            ans = input("Schvalujete brief k distribuci? [a = ano / n = ne]: ").strip().lower()
        except EOFError:
            ans = "n"
        approved = ans in ("a", "ano", "y", "yes")
    if approved:
        p_md, p_html = briefer.save(md, approved=True, suffix=suffix)
        log(A, f"SCHVALENO -> {p_html}")
    else:
        p_md, p_html = draft_md, draft_html
        log(A, "Neschvaleno - brief zustava jako NAVRH.")
    return {"brief_md": p_md, "brief_html": p_html, "schvaleno": approved, "analyza": an, "verifier": ver}
