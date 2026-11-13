"""Agent SCOUT - sleduje zdroje a stahuje data:
  * Registr verejnych zakazek / NEN / Vestnik (open data ISVZ)  - bez registrace
  * Registr smluv (XML dumpy)                                   - bez registrace
  * Hlidac statu API                                            - volitelne, token zdarma
  * Google News RSS                                             - bez registrace
  * ARES (profily konkurentu)                                   - bez registrace
Detekuje nove zakazky (porovnani s databazi) a preda je Extractoru.
"""
import json
import time
from datetime import date, datetime

from . import extractor
from .sources import rvz, smlouvy
from .sources.other import ares_firma, google_news, hlidac_zakazky
from .util import log, months_back, norm

A = "Scout"


def _save_zakazka(con, zak, vit, uc):
    now = datetime.now().isoformat(timespec="seconds")
    existed = con.execute("SELECT 1 FROM zakazky WHERE id=?", (zak["id"],)).fetchone() is not None
    cols = list(zak.keys()) + ["stazeno"]
    con.execute(f"INSERT OR REPLACE INTO zakazky ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})",
                [zak[c] for c in zak] + [now])
    con.execute("DELETE FROM vitezove WHERE zakazka_id=?", (zak["id"],))
    con.execute("DELETE FROM ucastnici WHERE zakazka_id=?", (zak["id"],))
    for v in vit:
        con.execute("INSERT OR REPLACE INTO vitezove (zakazka_id, dodavatel_ico, dodavatel_nazev, cena_bez_dph) VALUES (?,?,?,?)",
                    (zak["id"], v["dodavatel_ico"], v["dodavatel_nazev"], v["cena_bez_dph"]))
    for u in uc:
        con.execute("INSERT OR REPLACE INTO ucastnici (zakazka_id, dodavatel_ico, dodavatel_nazev, nabidkova_cena) VALUES (?,?,?,?)",
                    (zak["id"], u["dodavatel_ico"], u["dodavatel_nazev"], u["nabidkova_cena"]))
    return not existed


def scout_rvz(con, cfg, today=None):
    """Stahne mesicni open data RVZ za poslednich N mesicu, Extractor z nich vytahne zakazky
    a ulozi jen ty relevantni pro obor (CPV prefix nebo klicove slovo)."""
    obor = cfg["obory"][cfg["obor"]]
    base = cfg["zdroje"]["rvz_base"]
    nase = cfg.get("nase_ico") or None
    stats = {"souboru": 0, "zaznamu": 0, "relevantnich": 0, "novych": 0}
    months = months_back(cfg["mesice"] + 1, today)  # +1: aktualni mesic jeste neni zverejnen
    for i, (y, m) in enumerate(months):
        if (y, m) < (2024, 2):
            continue
        try:
            path = rvz.fetch_month(base, y, m, current=i >= len(months) - 3)
        except Exception as e:
            log(A, f"RVZ {m:02d}/{y}: chyba stahovani: {e}")
            continue
        if not path:
            rvz.log_missing(y, m)
            continue
        stats["souboru"] += 1
        n = rel = new = 0
        for rec in rvz.iter_records(path):
            n += 1
            if n % 20000 == 0:
                log(A, f"  {m:02d}/{y}: zpracovano {n} zaznamu...")
            zak, vit, uc = extractor.extract(rec, "rvz")
            if not zak["id"]:
                continue
            duvod = extractor.relevance(zak, obor)
            ours = nase and any(v["dodavatel_ico"] == nase for v in vit + uc)
            if not duvod and not ours:
                continue
            zak["relevance"] = duvod or "naše účast"
            rel += 1
            new += _save_zakazka(con, zak, vit, uc)
        con.commit()
        log(A, f"RVZ {m:02d}/{y}: {n} zaznamu, {rel} relevantnich, {new} novych")
        stats["zaznamu"] += n
        stats["relevantnich"] += rel
        stats["novych"] += new
    return stats


def scout_hlidac(con, cfg):
    token = cfg.get("hlidac_token")
    if not token:
        log(A, "Hlidac statu: token neni nastaven -> preskakuji (volitelny zdroj)")
        return {"preskoceno": True}
    obor = cfg["obory"][cfg["obor"]]
    dotaz = " OR ".join(f"cpv:{p}*" for p in obor["cpv_prefixy"][:4])
    log(A, f"Hlidac statu: dotaz '{dotaz}'")
    res = hlidac_zakazky(cfg["zdroje"]["hlidac_base"], token, dotaz)
    rel = new = 0
    for rec in res:
        zak, vit, uc = extractor.extract(rec, "hlidac")
        if not zak["id"]:
            continue
        zak["relevance"] = extractor.relevance(zak, obor) or "dotaz Hlídač státu"
        rel += 1
        new += _save_zakazka(con, zak, vit, uc)
    con.commit()
    log(A, f"Hlidac statu: {len(res)} zaznamu, {new} novych")
    return {"zaznamu": len(res), "novych": new}


def scout_smlouvy(con, cfg):
    """Registr smluv: posledni N mesicu dumpu, ulozi smlouvy relevantni pro obor
    nebo uzavrene se znamymi dodavateli (ICO vitezu z RVZ)."""
    base = cfg["zdroje"]["smlouvy_base"]
    obor = cfg["obory"][cfg["obor"]]
    kws = [" " + norm(k) + " " if len(norm(k)) <= 6 else norm(k) for k in obor["klicova_slova"]]
    icos = {r[0] for r in con.execute("SELECT DISTINCT dodavatel_ico FROM vitezove WHERE dodavatel_ico IS NOT NULL")}
    if cfg.get("nase_ico"):
        icos.add(cfg["nase_ico"])
    dumps = smlouvy.fetch_index(base)
    dumps.sort(key=lambda d: (d["rok"], d["mesic"]))
    dumps = dumps[-cfg.get("smlouvy_mesice", 3):]
    total = 0
    for d in dumps:
        try:
            path = smlouvy.fetch_dump(d)
        except Exception as e:
            log(A, f"Registr smluv {d['mesic']:02d}/{d['rok']}: {e}")
            continue
        if not path:
            continue
        n = rel = 0
        for s in smlouvy.iter_smlouvy(path):
            n += 1
            if not s["id"] or not smlouvy.is_relevant(s, kws, icos):
                continue
            rel += 1
            con.execute("INSERT OR REPLACE INTO smlouvy (id, predmet, datum_uzavreni, hodnota_bez_dph, hodnota_s_dph, "
                        "zadavatel_ico, zadavatel_nazev, url) VALUES (?,?,?,?,?,?,?,?)",
                        (s["id"], s["predmet"], s["datum_uzavreni"], s["hodnota_bez_dph"], s["hodnota_s_dph"],
                         s["zadavatel_ico"], s["zadavatel_nazev"], s["url"]))
            con.execute("DELETE FROM smlouvy_strany WHERE smlouva_id=?", (s["id"],))
            for st in s["strany"]:
                con.execute("INSERT INTO smlouvy_strany VALUES (?,?,?)", (s["id"], st["ico"], st["nazev"]))
        con.commit()
        total += rel
        log(A, f"Registr smluv {d['mesic']:02d}/{d['rok']}: {n} smluv, {rel} relevantnich")
    return {"relevantnich_smluv": total}


def scout_ares(con, cfg):
    """Doplni profily nejvetsich konkurentu z ARES (cache 30 dni)."""
    base = cfg["zdroje"]["ares_base"]
    rows = con.execute("""SELECT dodavatel_ico, COUNT(*) n FROM vitezove WHERE dodavatel_ico IS NOT NULL
                          GROUP BY dodavatel_ico ORDER BY n DESC LIMIT ?""", (cfg.get("ares_max_firem", 60),)).fetchall()
    icos = [r[0] for r in rows]
    if cfg.get("nase_ico"):
        icos.insert(0, cfg["nase_ico"])
    done = 0
    for ico in icos:
        row = con.execute("SELECT stazeno FROM firmy WHERE ico=?", (ico,)).fetchone()
        if row and row[0] and (date.today() - date.fromisoformat(row[0][:10])).days < 30:
            continue
        try:
            f = ares_firma(base, ico)
        except Exception as e:
            log(A, f"ARES {ico}: {e}")
            continue
        if f:
            f["stazeno"] = date.today().isoformat()
            con.execute("INSERT OR REPLACE INTO firmy (ico,nazev,sidlo,kraj,nace,pravni_forma,datum_vzniku,datum_zaniku,stazeno) "
                        "VALUES (:ico,:nazev,:sidlo,:kraj,:nace,:pravni_forma,:datum_vzniku,:datum_zaniku,:stazeno)", f)
            done += 1
        time.sleep(0.25)  # setrne k API
    con.commit()
    log(A, f"ARES: doplneno {done} profilu firem")
    return {"firem": done}


def scout_zpravy(con, cfg):
    base = cfg["zdroje"]["zpravy_base"]
    obor = cfg["obory"][cfg["obor"]]
    dotazy = [obor["zpravy_dotaz"]]
    top = con.execute("""SELECT COALESCE(f.nazev, v.dodavatel_nazev) n, COUNT(*) c FROM vitezove v
                         LEFT JOIN firmy f ON f.ico=v.dodavatel_ico GROUP BY v.dodavatel_ico ORDER BY c DESC LIMIT ?""",
                      (cfg.get("zpravy_max_konkurentu", 5),)).fetchall()
    dotazy += [f'"{r[0]}"' for r in top if r[0]]
    n = 0
    for q in dotazy:
        try:
            items = google_news(base, q)
        except Exception as e:
            log(A, f"Zpravy '{q}': {e}")
            continue
        for it in items:
            con.execute("INSERT OR REPLACE INTO zpravy (url,titulek,zdroj,datum,dotaz) VALUES (:url,:titulek,:zdroj,:datum,:dotaz)", it)
            n += 1
    con.commit()
    log(A, f"Zpravy (Google News RSS): {n} clanku")
    return {"clanku": n}
