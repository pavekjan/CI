"""Agent SCOUT - sleduje zdroje a stahuje data:
  * Registr verejnych zakazek / NEN / Vestnik (open data ISVZ)  - bez registrace
  * Registr smluv (XML dumpy)                                   - bez registrace
  * Hlidac statu API                                            - volitelne, token zdarma
  * Google News RSS                                             - bez registrace
  * ARES (profily konkurentu)                                   - bez registrace
Detekuje nove zakazky (porovnani s databazi) a preda je Extractoru.
"""
import os
import time
from collections import Counter, defaultdict
from datetime import date, datetime

from . import extractor
from .sources import rvz, smlouvy
from .sources.other import ares_firma, google_news, hlidac_zakazky
from .util import log, months_back, norm

A = "Scout"


def _save_zakazka(con, zak, vit, uc):
    """Ulozi zakazku. Open data obsahuji vic zaznamu tehoz rizeni (aktualizace) - novejsi zaznam
    prepise jen to, co skutecne obsahuje; prazdna pole a vitezove z drivejsiho zaznamu zustanou."""
    now = datetime.now().isoformat(timespec="seconds")
    old = con.execute("SELECT * FROM zakazky WHERE id=?", (zak["id"],)).fetchone()
    existed = old is not None
    if old:
        old = dict(old)
        zak = {k: (v if v not in (None, "", "neuvedeno") else old.get(k)) for k, v in zak.items()}
        if old.get("cpv_odhad") and zak.get("cpv_hlavni") == old.get("cpv_hlavni"):
            zak["cpv_odhad"] = old["cpv_odhad"]  # odhad segmentu zustava, dokud neprijde skutecne CPV
    cols = list(zak.keys()) + ["stazeno"]
    con.execute(f"INSERT OR REPLACE INTO zakazky ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})",
                [zak[c] for c in zak] + [now])
    # vitezove a ucastnici z vice zaznamu teze zakazky (casti, vysledek po castech) se scitaji, neprepisuji
    for v in vit:
        con.execute("INSERT OR REPLACE INTO vitezove (zakazka_id, dodavatel_ico, dodavatel_nazev, cena_bez_dph) VALUES (?,?,?,?)",
                    (zak["id"], v["dodavatel_ico"], v["dodavatel_nazev"], v["cena_bez_dph"]))
    for u in uc:
        con.execute("INSERT OR REPLACE INTO ucastnici (zakazka_id, dodavatel_ico, dodavatel_nazev, nabidkova_cena) VALUES (?,?,?,?)",
                    (zak["id"], u["dodavatel_ico"], u["dodavatel_nazev"], u["nabidkova_cena"]))
    return not existed


def _podpis(path):
    st = os.stat(path)
    return f"{st.st_size}-{int(st.st_mtime)}"


def _uz_zpracovano(con, klic, path):
    """True, pokud presne tento soubor (velikost+cas) uz byl zpracovan -> neni treba ho znovu parsovat."""
    row = con.execute("SELECT podpis FROM soubory WHERE klic=?", (klic,)).fetchone()
    return row is not None and row[0] == _podpis(path)


def _oznac_zpracovano(con, klic, path):
    con.execute("INSERT OR REPLACE INTO soubory VALUES (?,?)", (klic, _podpis(path)))
    con.commit()


def je_nedostupny(e):
    """Chyba spojeni (timeout, odmitnuti), ne chyba dat -> dalsi pokusy na stejny server nemaji smysl."""
    t = str(e).lower()
    return any(x in t for x in ("timed out", "timeout", "connection refused", "connecterror", "max retries", "name or service"))


PARALELNE_OD = 20 << 20  # soubory nad 20 MB se vytezuji ve vice procesech najednou


def _pool(cfg):
    """Vytezovani zaznamu (Extractor) je nejpomalejsi cast -> rozdelit na vic jader procesoru.
    Poradi zaznamu se zachova (imap), takze vysledek je stejny jako pri zpracovani po jednom."""
    n = int(cfg.get("procesu") or 0) or max(1, min(8, (os.cpu_count() or 2) - 1))
    if n < 2:
        return False
    try:
        import multiprocessing
        pool = multiprocessing.get_context("spawn").Pool(n)
        log(A, f"RVZ: zpracovavam na {n} jadrech procesoru najednou")
        return pool
    except Exception as e:  # napr. omezene prostredi -> po jednom
        log(A, f"RVZ: paralelni zpracovani neni k dispozici ({str(e)[:80]}), pokracuji po jednom")
        return False


def scout_rvz(con, cfg, today=None):
    stav = {"pool": None}
    try:
        return _scout_rvz(con, cfg, today, stav)
    finally:
        if stav["pool"]:
            stav["pool"].terminate()


def _zpracuj_soubor(con, cfg, path, ym, pool, obor, vse, nase, t0):
    """Projde jeden mesicni soubor RVZ a ulozi zakazky. Vrati (zaznamu, ulozeno, novych, bez cisla)."""
    y, m = ym
    n = rel = new = bez_id = 0
    t_log = t0
    zaznamy = rvz.iter_records(path)
    vytezene = (pool.imap(extractor.extract_rvz, zaznamy, chunksize=128) if pool
                else map(extractor.extract_rvz, zaznamy))
    for zak, vit, uc, pole in vytezene:
        n += 1
        if n % 200 == 0 and time.time() - t_log >= 5:
            t_log = time.time()
            log(A, f"  {m:02d}/{y}: zpracovano {n} zaznamu ({n / max(t_log - t0, 0.1):.0f}/s), ulozeno {rel}")
            con.commit()
        if not zak["id"]:
            bez_id += 1
            if bez_id == 1:  # diagnostika: jen nazvy poli (ne hodnoty), at je videt, co v zaznamu chybi
                log(A, f"  {m:02d}/{y}: zaznam bez cisla zakazky, pole: {', '.join(pole or [])}")
            continue
        if vse:
            duvod = next((o["nazev"] for k, o in cfg["obory"].items() if k != "vse" and extractor.relevance(zak, o)), "ostatní")
            ours = False
        else:
            duvod = extractor.relevance(zak, obor)
            ours = nase and any(v["dodavatel_ico"] == nase for v in vit + uc)
        if not duvod and not ours:
            continue
        zak["relevance"] = duvod or "naše účast"
        rel += 1
        new += _save_zakazka(con, zak, vit, uc)
    return n, rel, new, bez_id


def _scout_rvz(con, cfg, today, stav):
    """Stahne mesicni open data RVZ za poslednich N mesicu, Extractor z nich vytahne zakazky
    a ulozi jen ty relevantni pro obor (CPV prefix nebo klicove slovo)."""
    if cfg.get("rvz_preskocit"):  # jen Registr smluv (GitHub Actions, stahnout_registr_3roky.bat)
        log(A, "RVZ: v tomto rezimu se zakazky nestahuji (jen Registr smluv)")
        return {"preskoceno": True}
    obor = cfg["obory"][cfg["obor"]]
    vse = cfg["obor"] == "vse"  # aplikace: ukladame vsechny obory, aby slo profilovat libovolnou firmu
    base = cfg["zdroje"]["rvz_base"]
    nase = cfg.get("nase_ico") or None
    stats = {"souboru": 0, "zaznamu": 0, "relevantnich": 0, "novych": 0}
    months = months_back(cfg["mesice"] + 1, today)  # +1: aktualni mesic jeste neni zverejnen
    verze = con.execute("SELECT podpis FROM soubory WHERE klic='extractor_verze'").fetchone()
    # novy Extractor cte data jinak -> stare vytezene udaje zahodit a soubory zpracovat znovu. Ale az ve chvili,
    # kdy je prvni soubor opravdu k dispozici: kde ISVZ neodpovida (GitHub, Render), se nic nesmaze.
    prepocet = bool(verze and verze[0] != str(extractor.EXTRACTOR_VERZE)
                    or (not verze and con.execute("SELECT COUNT(*) FROM zakazky").fetchone()[0]))
    if not prepocet:
        con.execute("INSERT OR REPLACE INTO soubory VALUES ('extractor_verze', ?)", (str(extractor.EXTRACTOR_VERZE),))
        con.commit()
    nedostupne = 0  # server ISVZ nekdy z cloudu (napr. Render) vubec neodpovida -> nezkouset dalsi mesice
    for i, (y, m) in enumerate(months):
        if (y, m) < (2024, 2):
            continue
        if i < len(months) - 3 and con.execute("SELECT 1 FROM soubory WHERE klic=?", (
                f"rvz:rvz_VZ-{m:02d}-{y}.zip:{cfg['obor']}:{nase or ''}:x{extractor.EXTRACTOR_VERZE}",)).fetchone():
            continue  # starsi mesic uz je zpracovany a MMR ho uz nemeni -> ani nestahovat
        try:
            path = rvz.fetch_month(base, y, m, current=i >= len(months) - 3)
        except Exception as e:
            log(A, f"RVZ {m:02d}/{y}: chyba stahovani: {e}")
            if je_nedostupny(e):
                nedostupne += 1
                if nedostupne >= 2:
                    log(A, "RVZ: server ISVZ z tohoto pocitace/serveru neodpovida -> zbyvajici mesice preskakuji. "
                           "Online verze bere data z GitHubu (aktualizovat_online.bat nebo GitHub Actions, viz README).")
                    stats["nedostupne"] = True
                    break
            continue
        nedostupne = 0
        if not path:
            rvz.log_missing(y, m)
            continue
        if prepocet:
            log(A, f"Nová verze Extractoru ({extractor.EXTRACTOR_VERZE}): zpracovávám zakázky znovu "
                   "(už stažené soubory se berou z cache, starší měsíce se stáhnou znovu)")
            for t in ("vitezove", "ucastnici", "zakazky", "priznaky", "dodavatele"):
                # bezpecnost: t je konstanta z kodu (vedome potlaceni nalezu banditu, viz SECURITY.md)
                con.execute(f"DELETE FROM {t}")  # nosec B608
            con.execute("DELETE FROM soubory WHERE klic LIKE 'rvz:%'")
            con.execute("INSERT OR REPLACE INTO soubory VALUES ('extractor_verze', ?)", (str(extractor.EXTRACTOR_VERZE),))
            con.commit()
            prepocet = False
        stats["souboru"] += 1
        klic = f"rvz:{os.path.basename(path)}:{cfg['obor']}:{nase or ''}:x{extractor.EXTRACTOR_VERZE}"
        if _uz_zpracovano(con, klic, path):
            log(A, f"RVZ {m:02d}/{y}: beze zmeny od minula -> preskakuji (uz je v databazi)")
            continue
        t0 = time.time()
        log(A, f"RVZ {m:02d}/{y}: zpracovavam soubor (prubeh se vypisuje kazdych par sekund)...")
        if stav["pool"] is None and os.path.getsize(path) > PARALELNE_OD:
            stav["pool"] = _pool(cfg)
        try:
            n, rel, new, bez_id = _zpracuj_soubor(con, cfg, path, (y, m), stav["pool"] or None, obor, vse, nase, t0)
        except Exception as e:
            if not stav["pool"]:
                raise
            # chyba v paralelnim zpracovani -> stejny mesic znovu po jednom (ukladani je idempotentni)
            log(A, f"RVZ {m:02d}/{y}: paralelni zpracovani selhalo ({str(e)[:100]}), zpracuji znovu po jednom")
            stav["pool"].terminate()
            stav["pool"] = False
            n, rel, new, bez_id = _zpracuj_soubor(con, cfg, path, (y, m), None, obor, vse, nase, time.time())
        con.commit()
        _oznac_zpracovano(con, klic, path)
        log(A, f"RVZ {m:02d}/{y}: {n} zaznamu, {rel} ulozeno, {new} novych zakazek"
               + (f", {bez_id} bez cisla zakazky (preskoceno)" if bez_id else "")
               + (f", {n - rel - bez_id} mimo obor" if not vse and n - rel - bez_id else "")
               + f" ({time.time() - t0:.0f} s)")
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
    if not obor["cpv_prefixy"]:
        log(A, "Hlidac statu: v rezimu 'vse obory' se nepouziva (open data RVZ pokryvaji vse)")
        return {"preskoceno": True}
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


def _hodnota_smlouvy(s):
    if s["hodnota_bez_dph"]:
        return s["hodnota_bez_dph"]
    return (s["hodnota_s_dph"] or 0) / 1.21


def scout_smlouvy(con, cfg):
    """Registr smluv po mesicnich souborech (dumpech).
    - souhrn za `smlouvy_souhrn_mesice` mesicu (vychozi 36): u kazde firmy pocet a objem smluv po mesicich
      a s kym je uzavrela. Pokryva i male zakazky a objednavky, ktere v RVZ nejsou (napr. e-shopy).
    - cele smlouvy (predmet, odkaz) jen za poslednich `smlouvy_mesice` mesicu (overeni vitezu, detail).
    Hotove mesice se zpracuji jednou a pak se preskakuji, i bez stazeni souboru."""
    base = cfg["zdroje"]["smlouvy_base"]
    obor = cfg["obory"][cfg["obor"]]
    kws = [" " + norm(k) + " " if len(norm(k)) <= 6 else norm(k) for k in obor["klicova_slova"]]
    icos = {r[0] for r in con.execute("SELECT DISTINCT dodavatel_ico FROM vitezove WHERE dodavatel_ico IS NOT NULL")}
    if cfg.get("nase_ico"):
        icos.add(cfg["nase_ico"])
    detail_n = int(cfg.get("smlouvy_mesice", 3) or 0)
    souhrn_n = max(int(cfg.get("smlouvy_souhrn_mesice", 0) or 0), detail_n)
    if souhrn_n <= 0:
        log(A, "Registr smluv: vypnuto (smlouvy_mesice = 0) -> preskakuji")
        return {"preskoceno": True}
    if con.execute("SELECT 1 FROM soubory WHERE klic LIKE 'rs2:%' LIMIT 1").fetchone():
        # verze 10/11 brala z indexu i denni prirustky jako mesice -> souhrn prepocitat znovu
        con.execute("DELETE FROM smlouvy_souhrn")
        con.execute("DELETE FROM smlouvy_odberatele")
        con.execute("DELETE FROM soubory WHERE klic LIKE 'rs2:%'")
        con.commit()
    vybrane = smlouvy.vyber_dumpy(smlouvy.fetch_index(base), souhrn_n)
    mesice_detail = sorted({did[:7] for did, _ in vybrane})[-detail_n:] if detail_n else []
    log(A, f"Registr smluv: {len({did[:7] for did, _ in vybrane})} mesicu ({len(vybrane)} souboru), detail za {len(mesice_detail)}")
    total = smluv = novych = 0
    max_novych = int(cfg.get("smlouvy_max_novych") or 0)  # GitHub Actions: historii doplnovat po castech
    for dump_id, d in reversed(vybrane):  # od nejnovejsiho: aktualni data maji prednost, historie se doplni
        detail = dump_id[:7] in mesice_detail
        klic = f"rs3:{dump_id}"
        row = con.execute("SELECT podpis FROM soubory WHERE klic=?", (klic,)).fetchone()
        if (d["dokonceny"] or d["den"]) and row and (row[0].startswith("d:") or not detail):
            continue  # hotovy mesic uz je zpracovany -> nestahovat znovu
        if max_novych and novych >= max_novych:
            log(A, f"Registr smluv: dalsi starsi mesice doplni pristi beh (limit {max_novych} na beh)")
            break
        novych += 1
        try:
            path = smlouvy.fetch_dump(d)
        except Exception as e:
            log(A, f"Registr smluv {d['mesic']:02d}/{d['rok']}: {e}")
            continue
        if not path:
            continue
        podpis = ("d:" if detail else "s:") + _podpis(path)
        if row and row[0] == podpis:
            log(A, f"Registr smluv {d['mesic']:02d}/{d['rok']}: beze zmeny od minula -> preskakuji")
            continue
        souhrn, odber, nazvy = Counter(), Counter(), {}
        hodn, hodn_o = defaultdict(float), defaultdict(float)
        n = rel = 0
        t_log = time.time()
        for s in smlouvy.iter_smlouvy(path):
            n += 1
            if n % 5000 == 0 and time.time() - t_log >= 5:
                t_log = time.time()
                log(A, f"  Registr smluv {d['mesic']:02d}/{d['rok']}: zpracovano {n} smluv")
            h = _hodnota_smlouvy(s)
            mesic = (s["datum_uzavreni"] or "")[:7] or f"{d['rok']}-{d['mesic']:02d}"
            zad = s["zadavatel_ico"]
            if zad and s["zadavatel_nazev"]:
                nazvy[zad] = s["zadavatel_nazev"]
            for st in {x["ico"]: x for x in s["strany"] if x["ico"] and x["ico"] != zad}.values():
                souhrn[(st["ico"], mesic)] += 1
                hodn[(st["ico"], mesic)] += h
                if st["nazev"]:
                    nazvy[st["ico"]] = st["nazev"]
                if zad:
                    odber[(st["ico"], zad)] += 1
                    hodn_o[(st["ico"], zad)] += h
            if not detail or not s["id"] or (cfg["obor"] != "vse" and not smlouvy.is_relevant(s, kws, icos)):
                continue
            rel += 1
            con.execute("INSERT OR REPLACE INTO smlouvy (id, predmet, datum_uzavreni, hodnota_bez_dph, hodnota_s_dph, "
                        "zadavatel_ico, zadavatel_nazev, url) VALUES (?,?,?,?,?,?,?,?)",
                        (s["id"], s["predmet"], s["datum_uzavreni"], s["hodnota_bez_dph"], s["hodnota_s_dph"],
                         s["zadavatel_ico"], s["zadavatel_nazev"], s["url"]))
            con.execute("DELETE FROM smlouvy_strany WHERE smlouva_id=?", (s["id"],))
            for st in s["strany"]:
                con.execute("INSERT INTO smlouvy_strany VALUES (?,?,?)", (s["id"], st["ico"], st["nazev"]))
        con.execute("DELETE FROM smlouvy_souhrn WHERE dump=?", (dump_id,))
        con.execute("DELETE FROM smlouvy_odberatele WHERE dump=?", (dump_id,))
        con.executemany("INSERT INTO smlouvy_souhrn VALUES (?,?,?,?,?)",
                        [(ico, m, dump_id, c, hodn[(ico, m)]) for (ico, m), c in souhrn.items()])
        con.executemany("INSERT INTO smlouvy_odberatele VALUES (?,?,?,?,?)",
                        [(ico, z, dump_id, c, hodn_o[(ico, z)]) for (ico, z), c in odber.items()])
        con.executemany("INSERT OR REPLACE INTO subjekty VALUES (?,?)", list(nazvy.items()))
        con.commit()
        con.execute("INSERT OR REPLACE INTO soubory VALUES (?,?)", (klic, podpis))
        con.commit()
        if cfg.get("mazat_stazene"):  # GitHub Actions: male misto na disku -> zpracovany soubor smazat
            try:
                os.remove(path)
            except OSError:
                pass
        total += rel
        smluv += n
        log(A, f"Registr smluv {d['mesic']:02d}/{d['rok']}: {n} smluv" + (f", {rel} ulozeno v detailu" if detail else " (souhrn)"))
    return {"smluv": smluv, "detail": total}


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
