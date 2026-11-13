"""Export profilu firmy do Obsidianu jako knowledge graph.

Kazda entita je samostatna poznamka s YAML frontmatter a [[wikiodkazy]]:
    TenderScope/
      00_Prehled/      dossier firmy (shrnuti, skore, KIQ) - vstupni bod
      01_Firmy/        cilova firma a konkurenti
      02_Zadavatele/   zakaznici (zadavatele)
      03_Zakazky/      jednotlive zakazky (zadavatel, vitez, ucastnici, segment, zdroj)
      04_Segmenty/     oddily CPV
      05_Zjisteni/     zjisteni ze skore (fakt - zdroj - inference - alternativni hypoteza - dopad)
      06_Zdroje/       dukazy: datove sady, zaznamy ARES, smlouvy z Registru smluv, clanky (Admiralty rating)
      07_Mapy/         canvas mapa konkurencniho prostredi
Graf v Obsidianu (Ctrl+G) pak ukaze sit: firma - zakazky - zadavatele - konkurenti - zdroje.
Zadna informace bez zdroje: kazde tvrzeni odkazuje na poznamku ve 06_Zdroje.
"""
import io
import json
import os
import re
import zipfile
from datetime import date

from .util import clean_ico, log

A = "Obsidian"
ROOT_DIR = "TenderScope"

DIRS = {
    "prehled": "00_Prehled", "firmy": "01_Firmy", "zadavatele": "02_Zadavatele", "zakazky": "03_Zakazky",
    "segmenty": "04_Segmenty", "zjisteni": "05_Zjisteni", "zdroje": "06_Zdroje", "mapy": "07_Mapy",
}


def safe(name, maxlen=90):
    """Nazev souboru / wikiodkazu bez znaku, ktere Obsidian nebo Windows nesnasi."""
    s = re.sub(r'[\\/:*?"<>|#^\[\]]+', " ", str(name or "")).strip()
    s = re.sub(r"\s+", " ", s).strip(" .")
    return (s[:maxlen].rstrip(" .") or "bez nazvu")


def yml(v):
    if v is None:
        return "null"
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return f"{v:.2f}".rstrip("0").rstrip(".") if isinstance(v, float) else str(v)
    if isinstance(v, (list, tuple)):
        return "[" + ", ".join(yml(x) for x in v) + "]"
    return json.dumps(str(v), ensure_ascii=False)


def front(d):
    return "---\n" + "\n".join(f"{k}: {yml(v)}" for k, v in d.items()) + "\n---\n"


def kc(x):
    if x is None:
        return "–"
    if x >= 1e9:
        return f"{x / 1e9:.2f}".replace(".", ",") + " mld. Kč"
    if x >= 1e6:
        return f"{x / 1e6:.1f}".replace(".", ",") + " mil. Kč"
    return f"{x:,.0f} Kč".replace(",", " ")


def pc(x):
    return "–" if x is None else f"{x * 100:.0f} %"


class Vault:
    def __init__(self):
        self.files = {}  # relativni cesta -> obsah
        self.sources = {}  # klic -> (id, nazev)
        self.n_src = 0

    def put(self, folder, name, content):
        self.files[f"{ROOT_DIR}/{DIRS[folder]}/{safe(name)}.md"] = content
        return f"[[{safe(name)}]]"

    def source(self, key, title, url, publisher, reliability, credibility, typ, extract, proves, not_proves, accessed=None):
        """Poznamka-dukaz (S-xxx). Vraci wikiodkaz; stejny klic = stejna poznamka."""
        if key in self.sources:
            return f"[[{self.sources[key]}]]"
        self.n_src += 1
        sid = f"S-{self.n_src:03d}"
        name = f"{sid} {safe(title, 70)}"
        self.sources[key] = name
        body = front({"type": "evidence", "id": sid, "title": title, "source_type": typ, "publisher": publisher, "url": url,
                      "accessed": accessed or date.today().isoformat(), "reliability": reliability, "credibility": credibility,
                      "tags": ["tenderscope", "evidence", f"zdroj/{typ}"]})
        body += f"\n# {sid}: {title}\n\n**Admiralty rating:** {reliability}{credibility} · **Vydavatel:** {publisher}"
        if url:
            body += f" · [Otevřít zdroj]({url})"
        body += f"\n\n## Výtah\n{extract}\n\n## Co dokládá\n{proves}\n\n## Co nedokládá\n{not_proves}\n"
        self.files[f"{ROOT_DIR}/{DIRS['zdroje']}/{name}.md"] = body
        return f"[[{name}]]"

    def write_dir(self, base):
        n = 0
        for rel, content in self.files.items():
            path = os.path.join(base, *rel.split("/"))
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8", newline="\n") as f:
                f.write(content)
            n += 1
        return n

    def zip_bytes(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            for rel, content in self.files.items():
                z.writestr(rel, content)
        return buf.getvalue()


def export_firma(con, profil, cfg, exa_items=None, max_zakazek=60):
    """Postavi trezor pro jednu firmu z vysledku api.profil(). Vraci Vault."""
    p = profil
    v = Vault()
    today = date.today().isoformat()
    firm_name = safe(p["nazev"])
    firm_link = f"[[{firm_name}]]"

    # ---------------- zdroje (datove sady) ----------------
    s_rvz = v.source("rvz", "Registr veřejných zakázek – otevřená data ISVZ", "https://isvz.nipez.cz/opendata",
                     "Ministerstvo pro místní rozvoj ČR (ISVZ/NIPEZ)", "A", 1, "dataset",
                     "Měsíční JSON exporty Registru veřejných zakázek (NEN, Věstník VZ, Tender arena, TENDERMARKET), staženo a zpracováno agenty TenderScope (Scout, Extractor).",
                     "Údaje o zadávacích řízeních: zadavatel, předmět, CPV, předpokládaná hodnota, lhůty, účastníci, vybraní dodavatelé a smluvní ceny, jak je uveřejnili zadavatelé.",
                     "Úplnost: zakázky malého rozsahu mimo elektronické nástroje se nezveřejňují; u části řízení chybí účastníci nebo ceny. Data začínají únorem 2024.")
    s_rs = v.source("rs", "Registr smluv – otevřená data", "https://data.smlouvy.gov.cz/", "Digitální a informační agentura", "A", 1, "dataset",
                    "Měsíční XML dumpy metadat smluv uveřejněných podle zákona č. 340/2015 Sb.",
                    "Že smlouva mezi zadavatelem a dodavatelem byla uzavřena a uveřejněna, včetně hodnoty.",
                    "Že smlouva vzešla právě z konkrétního zadávacího řízení – párování se zakázkou je odvozené (Verifier: zadavatel + dodavatel + datum + cena).")
    s_tool = v.source("tenderscope", "TenderScope – výpočet skóre a metrik", None, "TenderScope (vlastní analýza)", "C", 2, "analyza",
                      "Agregace a skóre spočtené agentem Analyst z dat v databázi TenderScope k " + today + ".",
                      "Výsledek výpočtu nad uvedenými daty a metodikou (váhy složek viz dossier).",
                      "Nejde o nezávislý zdroj; kvalita závisí na úplnosti otevřených dat.")

    ares = p.get("ares") or {}
    s_ares = {}

    def ares_src(ico, nazev, rec=None):
        if ico in s_ares:
            return s_ares[ico]
        rec = rec or {}
        extract = f"Subjekt {nazev}, IČO {ico}" + (f", sídlo {rec.get('sidlo')}" if rec.get("sidlo") else "") + \
                  (f", vznik {rec.get('datum_vzniku')}" if rec.get("datum_vzniku") else "") + \
                  (f", zánik {rec.get('datum_zaniku')}" if rec.get("datum_zaniku") else "") + \
                  (f", NACE {rec.get('nace')}" if rec.get("nace") else "") + "."
        s_ares[ico] = v.source(f"ares:{ico}", f"ARES – {nazev}", f"https://ares.gov.cz/ekonomicke-subjekty?ico={ico}",
                               "Ministerstvo financí ČR (ARES)", "A", 1, "registr", extract,
                               "Identitu, sídlo a právní stav subjektu.", "Nic o kvalitě dodávek ani o vztazích s konkurenty.")
        return s_ares[ico]

    firmy_db = {r["ico"]: dict(r) for r in con.execute("SELECT * FROM firmy")}

    # ---------------- segmenty ----------------
    seg_links = {}
    for s in p["segmenty"]:
        seg_links[s["segment"]] = f"[[CPV {safe(s['segment'])}]]"
    for z in p["zakazky"]:
        seg_links.setdefault(z["segment"], f"[[CPV {safe(z['segment'])}]]")

    # ---------------- zakazky ----------------
    zak = p["zakazky"][:max_zakazek]
    ids = [z["id"] for z in zak]
    ucast = {}
    vitez = {}
    zdet = {}
    if ids:
        con.execute("CREATE TEMP TABLE IF NOT EXISTS t_exp (id TEXT PRIMARY KEY)")
        con.execute("DELETE FROM t_exp")
        con.executemany("INSERT OR IGNORE INTO t_exp VALUES (?)", [(i,) for i in ids])
        for r in con.execute("SELECT * FROM ucastnici WHERE zakazka_id IN (SELECT id FROM t_exp)"):
            ucast.setdefault(r["zakazka_id"], []).append(dict(r))
        for r in con.execute("SELECT * FROM vitezove WHERE zakazka_id IN (SELECT id FROM t_exp)"):
            vitez.setdefault(r["zakazka_id"], []).append(dict(r))
        for r in con.execute("SELECT * FROM zakazky WHERE id IN (SELECT id FROM t_exp)"):
            zdet[r["id"]] = dict(r)
    nazvy = {r["ico"]: r["nazev"] for r in con.execute("SELECT ico, nazev FROM dodavatele")}

    def firm_note_name(ico, nazev=None):
        return safe(firmy_db.get(ico, {}).get("nazev") or nazvy.get(ico) or nazev or ico)

    zad_tenders = {}   # zadavatel -> [zakazka links]
    comp_tenders = {}  # konkurent ico -> [zakazka links]
    seg_tenders = {}
    for z in zak:
        d = zdet.get(z["id"], {})
        zname = safe(f"VZ {(z['nazev'] or '')[:70]} ({z['id'].split(':')[-1]})", 100)
        zlink = f"[[{zname}]]"
        zad_name = safe(z["zadavatel"] or d.get("zadavatel_ico") or "neznámý zadavatel")
        zad_tenders.setdefault((zad_name, d.get("zadavatel_ico")), []).append(zlink)
        seg_tenders.setdefault(z["segment"], []).append(zlink)
        vit_links, uc_links = [], []
        for w in vitez.get(z["id"], []):
            nm = firm_note_name(w["dodavatel_ico"], w["dodavatel_nazev"])
            vit_links.append(f"[[{nm}]]")
            if w["dodavatel_ico"] and w["dodavatel_ico"] != p["ico"]:
                comp_tenders.setdefault(w["dodavatel_ico"], []).append(zlink)
        for u in ucast.get(z["id"], []):
            nm = firm_note_name(u["dodavatel_ico"], u["dodavatel_nazev"])
            uc_links.append(f"[[{nm}]]")
            if u["dodavatel_ico"] and u["dodavatel_ico"] != p["ico"]:
                comp_tenders.setdefault(u["dodavatel_ico"], []).append(zlink)
        src = [s_rvz]
        s_nen = None
        if z.get("url"):
            s_nen = v.source(f"nen:{z['id']}", f"Detail zakázky {z['id'].split(':')[-1]}", z["url"], "NEN / Věstník veřejných zakázek",
                             "A", 1, "zakazka", f"Veřejný detail zadávacího řízení „{z['nazev']}“ ({z['zadavatel']}).",
                             "Existenci řízení, zadávací dokumentaci a oznámení o výsledku.", "Kvalitu plnění.")
            src.append(s_nen)
        if z.get("overeno_rs"):
            sm = con.execute("SELECT s.* FROM vitezove v JOIN smlouvy s ON s.id=v.smlouva_id WHERE v.zakazka_id=? AND v.dodavatel_ico=?",
                             (z["id"], p["ico"])).fetchone()
            if sm:
                src.append(v.source(f"rs:{sm['id']}", f"Smlouva {sm['id']} – {sm['zadavatel_nazev']}", sm["url"], "Registr smluv", "A", 1, "smlouva",
                                    f"Smlouva „{sm['predmet']}“, uzavřena {sm['datum_uzavreni']}, hodnota bez DPH {kc(sm['hodnota_bez_dph'])}.",
                                    "Uzavření smlouvy mezi zadavatelem a firmou a její hodnotu.",
                                    "Že jde přesně o tuto zakázku – párování provedl Verifier (zadavatel, dodavatel, datum, cena)."))
        vysl = "výhra" if z["vysledek"] == "výhra" else "neúspěch"
        body = front({
            "type": "zakazka", "id": z["id"], "nazev": z["nazev"], "zadavatel": f"[[{zad_name}]]",
            "segment": seg_links.get(z["segment"]), "cpv": d.get("cpv_hlavni"), "datum_zahajeni": z["datum"],
            "lhuta_nabidek": (d.get("lhuta_nabidek") or "")[:10] or None, "predpokladana_hodnota": z["odhad"],
            "cena_bez_dph": z["cena"], "pocet_nabidek": z["nabidek"], "stav": d.get("stav"), "postup": d.get("postup"),
            "kraj": d.get("kraj"), "vitezove": vit_links, "ucastnici": uc_links, "vysledek_cilove_firmy": vysl,
            "overeno_registr_smluv": bool(z.get("overeno_rs")), "sources": src, "tags": ["tenderscope", "zakazka", f"vysledek/{vysl}"],
        })
        body += f"\n# {z['nazev']}\n\n"
        body += f"Zadavatel [[{zad_name}]] zahájil řízení {z['datum'] or '?'} v segmentu {seg_links.get(z['segment'])}. "
        body += f"Předpokládaná hodnota {kc(z['odhad'])}, počet nabídek {z['nabidek'] or 'neuveden'} ({', '.join(src[:2])}).\n\n"
        body += f"**Vítěz:** {', '.join(vit_links) or 'neuveden'}" + (f" za {kc(z['cena'])}" if z["vysledek"] == "výhra" and z["cena"] else "") + "\n\n"
        if uc_links:
            body += f"**Účastníci:** {', '.join(uc_links)}\n\n"
        body += f"**Výsledek pro {firm_link}:** {vysl}" + (" · smlouva dohledána v Registru smluv" if z.get("overeno_rs") else "") + "\n\n"
        if d.get("kriteria"):
            body += f"**Hodnoticí kritéria:** {d['kriteria']}\n\n"
        if z.get("url"):
            body += f"[Detail na NEN / VVZ]({z['url']})\n"
        v.files[f"{ROOT_DIR}/{DIRS['zakazky']}/{zname}.md"] = body

    # ---------------- zadavatele ----------------
    kl = {k["ico"]: k for k in p["klienti"]}
    for (zad_name, zico), links in zad_tenders.items():
        k = kl.get(zico, {})
        src = [s_rvz] + ([ares_src(zico, zad_name)] if zico else [])
        body = front({"type": "entity", "entity_class": "zadavatel", "name": zad_name, "ico": zico,
                      "vyhry_firmy": k.get("vyhry", 0), "objem_pro_firmu": k.get("objem"),
                      "relations": [firm_link], "sources": src, "tags": ["tenderscope", "entity", "zadavatel"]})
        body += f"\n# {zad_name}\n\nZadavatel (veřejný zákazník)" + (f", IČO {zico}" if zico else "") + ". "
        if k:
            body += f"Firmě {firm_link} zadal {k['vyhry']} zakázek za {kc(k['objem'])} ({src[0]}).\n"
        else:
            body += f"Firma {firm_link} se u něj ucházela o zakázky ({src[0]}).\n"
        body += "\n## Zakázky\n" + "\n".join(f"- {l}" for l in links) + "\n"
        v.files[f"{ROOT_DIR}/{DIRS['zadavatele']}/{zad_name}.md"] = body

    # ---------------- konkurenti ----------------
    comp = {}
    for s in p["souboje"]:
        comp[s["ico"]] = {"nazev": s["nazev"], "stretu": s["stretu"], "my": s["my_vyhra"], "oni": s["oni_vyhra"], "objem": None}
    for r in p["rivalove"]:
        comp.setdefault(r["ico"], {"nazev": r["nazev"], "stretu": 0, "my": 0, "oni": 0})
        comp[r["ico"]]["objem"] = r["objem"]
        comp[r["ico"]]["vyhry_seg"] = r["vyhry"]
    for ico, c in comp.items():
        if not clean_ico(ico):
            continue
        nm = firm_note_name(ico, c["nazev"])
        rec = firmy_db.get(ico)
        src = [s_rvz] + ([ares_src(ico, nm, rec)] if rec else [])
        links = sorted(set(comp_tenders.get(ico, [])))
        body = front({"type": "entity", "entity_class": "dodavatel", "role": "konkurent", "name": nm, "ico": ico,
                      "spolecnych_soutezi": c["stretu"], "vyhry_cilove_firmy": c["my"], "vyhry_konkurenta": c["oni"],
                      "objem_v_segmentech": c.get("objem"), "relations": [firm_link], "sources": src,
                      "tags": ["tenderscope", "entity", "dodavatel", "konkurent"]})
        body += f"\n# {nm}\n\nKonkurent firmy {firm_link}"
        if c["stretu"]:
            body += f": potkali se v {c['stretu']} soutěžích, {firm_link} vyhrála {c['my']}×, {nm} {c['oni']}× ({src[0]})."
        else:
            body += " ve stejných segmentech (bez přímého střetu v datech)."
        if c.get("objem"):
            body += f" V segmentech cílové firmy vyhrál zakázky za {kc(c['objem'])} ({c.get('vyhry_seg', '?')}×)."
        if rec and rec.get("sidlo"):
            body += f"\n\nSídlo {rec['sidlo']} ({src[-1]})."
        if links:
            body += "\n\n## Společné zakázky\n" + "\n".join(f"- {l}" for l in links)
        v.files[f"{ROOT_DIR}/{DIRS['firmy']}/{nm}.md"] = body + "\n"

    # ---------------- segmenty ----------------
    for seg, link in seg_links.items():
        s = next((x for x in p["segmenty"] if x["segment"] == seg), None)
        name = link[2:-2]
        body = front({"type": "segment", "cpv_oddil": seg[:2], "name": seg, "podil_firmy": s["podil"] if s else None,
                      "poradi_firmy": s["poradi"] if s else None, "objem_trhu": s["trh_objem"] if s else None,
                      "sources": [s_rvz], "tags": ["tenderscope", "segment"]})
        body += f"\n# Segment {seg}\n\nOddíl CPV {seg[:2]}."
        if s:
            body += (f" {firm_link} v něm vyhrála {s['vyhry']} zakázek za {kc(s['objem'])}, tj. {pc(s['podil'])} objemu segmentu "
                     f"({s['poradi']}. z {s['dodavatelu']} dodavatelů). Vítězná cena firmy {pc(s['median_pomer'])} odhadu, trh {pc(s['trh_median_pomer'])} ({s_rvz}).")
        body += "\n\n## Zakázky\n" + "\n".join(f"- {l}" for l in seg_tenders.get(seg, [])) + "\n"
        v.files[f"{ROOT_DIR}/{DIRS['segmenty']}/{name}.md"] = body

    # ---------------- zpravy / Exa ----------------
    news_links = []
    for n in (exa_items or []) + (p.get("zpravy") or []):
        if not n.get("url"):
            continue
        is_exa = n.get("zdroj") == "Exa"
        news_links.append(v.source(f"web:{n['url']}", n.get("titulek") or n["url"], n["url"], n.get("zdroj") or "web",
                                   "C", 3, "web",
                                   (n.get("text") or n.get("titulek") or "")[:600] + (f" (publikováno {n['datum']})" if n.get("datum") else ""),
                                   "Kontext – zmínku o firmě v médiích / na webu.",
                                   "Neověřeno z primárního zdroje; nalezeno " + ("vyhledáváním Exa." if is_exa else "přes Google News RSS.")))

    # ---------------- zjisteni (ze skore) ----------------
    find_links = []
    for i, s in enumerate(p["skore"]["slozky"], 1):
        if s["skore"] is None:
            continue
        fid = f"F-{p['ico']}-{i:02d}"
        name = f"{fid} {s['nazev']}"
        sev = "silná stránka" if s["skore"] >= 65 else ("neutrální" if s["skore"] >= 40 else "slabina")
        alt = {
            "uspesnost": "Nízký počet soutěží se známými účastníky může win rate zkreslit; firma může podávat nabídky jen tam, kde má jistotu.",
            "pozice": "Velký objem může tvořit jedna či dvě velké zakázky (rámcové smlouvy), ne stabilní pozice.",
            "cena": "Nízký poměr ceny k odhadu může znamenat nadhodnocené odhady zadavatelů, ne nižší ceny firmy.",
            "klienti": "Rozptyl zákazníků může být dán krátkým obdobím dat; dlouhodobě může dominovat jeden klient.",
            "trend": "Výkyv mezi pololetími může být sezónní (rozpočtový cyklus veřejného sektoru).",
        }.get(s["klic"], "")
        body = front({"type": "finding", "id": fid, "title": s["nazev"], "entity": firm_link, "skore": s["skore"], "vaha": s["vaha"],
                      "hodnoceni": sev, "confidence": "medium", "evidence": [s_rvz, s_tool], "tags": ["tenderscope", "finding", f"skore/{s['klic']}"]})
        body += (f"\n# {fid}: {s['nazev']} – {s['skore']}/100\n\n## Fakt\n{s['vysvetleni']}\n\n## Zdroj\n{s_rvz}, {s_tool}\n\n"
                 f"## Inference\nSložka hodnocena jako **{sev}** (váha {s['vaha']} % celkového skóre).\n\n## Alternativní hypotéza\n{alt}\n\n"
                 f"## Dopad pro rozhodnutí bid/no-bid\n" +
                 ("Při soutěži proti této firmě počítat s tím, že je v této dimenzi silná." if s["skore"] >= 65 else
                  "V této dimenzi je firma zranitelná – prostor pro konkurenční výhodu." if s["skore"] < 40 else
                  "Bez výrazné výhody či nevýhody.") + "\n")
        v.files[f"{ROOT_DIR}/{DIRS['zjisteni']}/{name}.md"] = body
        find_links.append(f"[[{name}]]")

    # ---------------- cilova firma ----------------
    k = p["kpi"]
    src_firma = [s_rvz, ares_src(p["ico"], firm_name, ares)] + ([s_rs] if k["smluv_rs"] else [])
    comp_links = [f"[[{firm_note_name(i, c['nazev'])}]]" for i, c in comp.items() if clean_ico(i)]
    client_links = [f"[[{safe(z[0])}]]" for z in zad_tenders]
    body = front({"type": "entity", "entity_class": "dodavatel", "role": "cil", "name": firm_name, "ico": p["ico"],
                  "sidlo": ares.get("sidlo"), "nace": ares.get("nace"), "skore": p["skore"]["celkem"], "hodnoceni": p["skore"]["hodnoceni"],
                  "vyhry": k["vyhry"], "ucasti": k["ucasti"], "win_rate": k["win_rate"], "objem_kc": k["objem"],
                  "segmenty": list(seg_links.values()), "zakaznici": client_links[:20], "konkurenti": comp_links[:20],
                  "zjisteni": find_links, "sources": src_firma + news_links[:10], "updated": today,
                  "tags": ["tenderscope", "entity", "dodavatel", "cil"]})
    body += f"\n# {firm_name}\n\nIČO {p['ico']}" + (f", sídlo {ares['sidlo']}" if ares.get("sidlo") else "") + f" ({src_firma[1]}).\n\n"
    body += f"Dossier: [[{firm_name} – dossier]]\n\n"
    body += f"## Konkurenti\n" + "\n".join(f"- {l}" for l in comp_links) + "\n\n"
    body += f"## Zákazníci\n" + "\n".join(f"- {l}" for l in client_links) + "\n\n"
    body += f"## Segmenty\n" + "\n".join(f"- {l}" for l in seg_links.values()) + "\n"
    if news_links:
        body += "\n## Zprávy a web\n" + "\n".join(f"- {l}" for l in news_links) + "\n"
    v.files[f"{ROOT_DIR}/{DIRS['firmy']}/{firm_name}.md"] = body

    # ---------------- dossier ----------------
    sk = p["skore"]
    d = front({"type": "case", "entity": firm_link, "skore": sk["celkem"], "hodnoceni": sk["hodnoceni"], "datum": today,
               "kit": "Konkurenční pozice dodavatele ve veřejných zakázkách pro rozhodnutí bid/no-bid",
               "sources": [s_rvz, s_rs, s_tool], "tags": ["tenderscope", "case"]})
    d += f"\n# {firm_name} – dossier konkurenceschopnosti\n\n"
    d += f"**Skóre {sk['celkem']}/100 – {sk['hodnoceni'] or 'nelze určit'}** ({s_tool})\n\n"
    d += "| Složka | Skóre | Váha | Zjištění |\n|---|---|---|---|\n"
    for s, fl in zip([x for x in sk["slozky"] if x["skore"] is not None], find_links):
        d += f"| {s['nazev']} | {s['skore']} | {s['vaha']} % | {fl} |\n"
    d += (f"\n## KIQ: Jak si firma stojí?\n- Vyhrané zakázky: **{k['vyhry']}** z {k['ucasti']} účastí, win rate {pc(k['win_rate'])} ({s_rvz})\n"
          f"- Objem výher: **{kc(k['objem'])}**, medián zakázky {kc(k['median_cena'])}\n"
          f"- Cena vs. odhad: {pc(k['median_pomer'])} (trh {pc(k['trh_median_pomer'])})\n"
          f"- Zákazníků: {k['klientu']}; smluv v Registru smluv: {k['smluv_rs']} ({s_rs})\n"
          f"- Výhry potvrzené v Registru smluv: {k['overeno_rs']} z {k['vyhry']}\n")
    d += "\n## Segmenty\n" + "\n".join(f"- {seg_links[s['segment']]}: {kc(s['objem'])}, podíl {pc(s['podil'])}, {s['poradi']}. místo" for s in p["segmenty"]) + "\n"
    d += "\n## Přímí konkurenti\n" + "\n".join(
        f"- [[{firm_note_name(s['ico'], s['nazev'])}]]: {s['stretu']}× spolu, skóre {s['my_vyhra']}:{s['oni_vyhra']}" for s in p["souboje"][:10]) + "\n"
    d += "\n## Otevřené příležitosti\n" + ("\n".join(f"- [{o['nazev']}]({o['url']}) – {o['zadavatel']}, {kc(o['hodnota'])}, lhůta {o['lhuta']}"
                                                    + (" · stávající klient" if o["klient"] else "") for o in p["prilezitosti"][:10]) or "- žádné v datech") + "\n"
    d += f"\n## Mapa\n![[{firm_name}.canvas]]\n\n## Metodika\nData: {s_rvz}, {s_rs}, ARES. Agenti Scout → Extractor → Verifier → Analyst. " \
         "Každá poznamka odkazuje na zdroj ve složce 06_Zdroje (Admiralty rating: A1 = oficiální registr, C3 = webový zdroj).\n"
    v.files[f"{ROOT_DIR}/{DIRS['prehled']}/{firm_name} – dossier.md"] = d

    # ---------------- canvas ----------------
    nodes, edges = [], []

    def node(nid, path, x, y, color=None, w=250, h=70):
        n = {"id": nid, "type": "file", "file": path, "x": x, "y": y, "width": w, "height": h}
        if color:
            n["color"] = color
        nodes.append(n)

    node("firma", f"{ROOT_DIR}/{DIRS['firmy']}/{firm_name}.md", -125, -35, "4", 250, 70)
    import math
    comps = [(i, c) for i, c in comp.items() if clean_ico(i)][:12]
    for j, (i, c) in enumerate(comps):
        ang = math.pi + math.pi * (j + 0.5) / max(1, len(comps))
        x, y = int(700 * math.cos(ang)) - 125, int(420 * math.sin(ang)) - 35
        nm = firm_note_name(i, c["nazev"])
        node(f"k{j}", f"{ROOT_DIR}/{DIRS['firmy']}/{nm}.md", x, y, "1")
        lab = f"{c['my']}:{c['oni']}" if c["stretu"] else "segment"
        edges.append({"id": f"ek{j}", "fromNode": "firma", "toNode": f"k{j}", "label": lab, "color": "1"})
    zads = list(zad_tenders.keys())[:12]
    for j, (zn, _) in enumerate(zads):
        ang = math.pi * (j + 0.5) / max(1, len(zads))
        x, y = int(700 * math.cos(ang)) - 125, int(420 * math.sin(ang)) - 35
        node(f"z{j}", f"{ROOT_DIR}/{DIRS['zadavatele']}/{zn}.md", x, y, "5")
        edges.append({"id": f"ez{j}", "fromNode": "firma", "toNode": f"z{j}", "color": "5"})
    for j, (seg, link) in enumerate(list(seg_links.items())[:6]):
        node(f"s{j}", f"{ROOT_DIR}/{DIRS['segmenty']}/{link[2:-2]}.md", 1000, -300 + j * 110, "3", 260, 60)
        edges.append({"id": f"es{j}", "fromNode": "firma", "toNode": f"s{j}", "color": "3"})
    nodes.append({"id": "legenda", "type": "text", "x": -1100, "y": -520, "width": 330, "height": 150,
                  "text": "**Legenda**\n- modrá: analyzovaná firma\n- červená: konkurenti (popisek = výhry firmy : konkurenta)\n- fialová: zákazníci\n- žlutá: segmenty CPV"})
    v.files[f"{ROOT_DIR}/{DIRS['mapy']}/{firm_name}.canvas"] = json.dumps({"nodes": nodes, "edges": edges}, ensure_ascii=False, indent=1)

    # README trezoru
    v.files[f"{ROOT_DIR}/README.md"] = (
        "# TenderScope – knowledge graph\n\nExport z aplikace TenderScope. Začněte v `00_Prehled`, graf otevřete Ctrl+G "
        "(doporučení: v nastavení grafu Groups podle `path:TenderScope/01_Firmy`, `/02_Zadavatele`, `/03_Zakazky`, `/06_Zdroje`).\n\n"
        "| Složka | Obsah |\n|---|---|\n| 00_Prehled | dossier firmy |\n| 01_Firmy | cílová firma a konkurenti |\n| 02_Zadavatele | zákazníci |\n"
        "| 03_Zakazky | zakázky |\n| 04_Segmenty | oddíly CPV |\n| 05_Zjisteni | zjištění ze skóre |\n| 06_Zdroje | důkazy s Admiralty ratingem |\n| 07_Mapy | canvas |\n")
    log(A, f"export {firm_name}: {len(v.files)} poznamek, {v.n_src} zdroju")
    return v


# ---------------- Exa (volitelne) ----------------
def exa_search(api_key, query, n=6):
    """Webove vyhledavani Exa (https://exa.ai). Potrebuje API klic v config.json -> exa_api_key."""
    if not api_key:
        return []
    from .util import session
    try:
        r = session().post("https://api.exa.ai/search", headers={"x-api-key": api_key, "Content-Type": "application/json"},
                           json={"query": query, "numResults": n, "type": "auto", "contents": {"text": {"maxCharacters": 600}}},
                           timeout=25)
        if r.status_code != 200:
            log(A, f"Exa: HTTP {r.status_code} {r.text[:200]}")
            return []
        out = []
        for it in r.json().get("results", []):
            out.append({"titulek": it.get("title") or it.get("url"), "url": it.get("url"), "datum": (it.get("publishedDate") or "")[:10] or None,
                        "zdroj": "Exa", "text": (it.get("text") or "").strip().replace("\n", " ")})
        return out
    except Exception as e:
        log(A, f"Exa: {e}")
        return []
