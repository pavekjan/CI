"""Agent BRIEFER - sestavi brief (Markdown + HTML) s prilezitostmi, konkurenci a doporucenim."""
import html
import os
import re
from datetime import date

from .util import OUT_DIR, log

A = "Briefer"


def kc(x):
    if x is None:
        return "–"
    if x >= 1e9:
        return f"{x / 1e9:.2f}".replace(".", ",") + " mld. Kč"
    if x >= 1e6:
        return f"{x / 1e6:.1f}".replace(".", ",") + " mil. Kč"
    return f"{x:,.0f} Kč".replace(",", " ")


def pct(x):
    return "–" if x is None else f"{x * 100:.0f} %"


def _cell(s):
    return str(s if s is not None else "–").replace("|", "/").replace("\n", " ")


def table(header, rows):
    out = ["| " + " | ".join(header) + " |", "|" + "|".join("---" for _ in header) + "|"]
    out += ["| " + " | ".join(_cell(c) for c in r) + " |" for r in rows]
    return "\n".join(out)


def build(an, ver, cfg, run_stats, zpravy, typ="denní"):
    obor = cfg["obory"][cfg["obor"]]["nazev"]
    k1, k3 = an["kiq1"], an["kiq3"]
    pr = an["prilezitosti"]
    L = []
    L.append(f"# TenderScope – {typ} brief: {obor}")
    L.append(f"*Vygenerováno {an['dnes']} · období od {an['obdobi_od']} · KIT: sledování veřejných zakázek v segmentu "
             f"{obor} a konkurenční pozice dodavatelů pro rozhodnutí bid/no-bid.*")
    L.append("")
    L.append("## Shrnutí pro vedení")
    bid = [p for p in pr if p["doporuceni"] == "BID"]
    L.append(f"- **{k1['pocet']}** relevantních zakázek za období, souhrnná předpokládaná hodnota **{kc(k1['celkova_hodnota'])}** "
             f"(hodnotu uvádí {k1['s_hodnotou']} z nich).")
    L.append(f"- **{len(pr)}** zakázek je právě otevřených, z toho **{len(bid)}** s doporučením BID.")
    if an["konkurenti"]:
        t = an["konkurenti"][0]
        L.append(f"- Největší konkurent podle objemu: **{t['nazev']}** ({t['vyhry']} výher, {kc(t['objem'])}, "
                 f"{pct(t['podil_trhu'])} sledovaného objemu).")
    if k3["median_pomer_cena"]:
        L.append(f"- Vítězné ceny jsou v mediánu na **{pct(k3['median_pomer_cena'])}** předpokládané hodnoty.")
    L.append(f"- Kvalita dat: {ver.get('overeno_v_rs', 0)} z {ver.get('vitezu', 0)} vítězů potvrzeno i v Registru smluv "
             f"({pct(ver.get('podil_overenych'))}); duplicit {ver.get('duplicita', 0)}, bez CPV {ver.get('chybi_cpv', 0)}, "
             f"bez hodnoty {ver.get('chybi_hodnota', 0)}.")
    L.append("")

    L.append("## Doporučení: otevřené příležitosti (KIQ 4)")
    if pr:
        L.append(table(["Skóre", "Doporučení", "Zakázka", "Zadavatel", "Hodnota", "Lhůta", "Proč"],
                       [[p["skore"], f"**{p['doporuceni']}**",
                         f"[{p['nazev'] or p['id']}]({p['url']})" if p["url"] else (p["nazev"] or p["id"]),
                         p["zadavatel_nazev"], kc(p["predpokladana_hodnota"]), (p["lhuta_nabidek"] or "")[:10],
                         "; ".join(p["duvody"])] for p in pr[:15]]))
        L.append("\n*Skóre 0–100 je pravidlové (obor, velikost, intenzita konkurence, vztah k zadavateli, čas na podání). "
                 "BID ≥ 60, ZVÁŽIT 40–59, NO-BID < 40. Konečné rozhodnutí patří člověku.*")
    else:
        L.append("V datech nejsou otevřené zakázky s lhůtou v budoucnu. Pozn.: open data RVZ vycházejí měsíčně (~5. den), "
                 "pro čerstvé výzvy sledujte profily zadavatelů / NEN nebo zapněte Hlídač státu.")
    if an["zrusene"]:
        L.append("\n**Zrušené zakázky (možné opakování soutěže):**")
        for z in an["zrusene"][:10]:
            L.append(f"- {z['nazev']} – {z['zadavatel_nazev'] or z['zadavatel_ico']} ({kc(z['predpokladana_hodnota'])}, {z['datum_zahajeni']})")
    L.append("")

    L.append("## KIQ 1: Co bylo vyhlášeno")
    L.append(table(["Segment (CPV)", "Počet"], k1["po_cpv"]))
    L.append("")
    L.append(table(["Kraj (místo plnění)", "Počet"], k1["po_krajich"][:10]))
    L.append("")
    L.append(table(["Měsíc", "Počet"], k1["po_mesicich"]))
    L.append("\n**Největší zakázky:**")
    L.append(table(["Zakázka", "Zadavatel", "Hodnota", "Stav"],
                   [[z["nazev"], z["zadavatel_nazev"], kc(z["predpokladana_hodnota"]), z["stav"]] for z in k1["top_hodnota"]]))
    L.append("")

    L.append("## KIQ 2: Kdo vyhrává a za kolik")
    L.append(table(["#", "Dodavatel", "IČO", "Výhry", "Účasti", "Win rate", "Objem", "Podíl", "Cena vs. odhad", "Zadavatelů", "Hlavní segment"],
                   [[i + 1, ("**" + k["nazev"] + "** (my)") if k["nase"] else k["nazev"], k["ico"], k["vyhry"], k["ucasti"],
                     pct(k["win_rate"]), kc(k["objem"]), pct(k["podil_trhu"]), pct(k["median_pomer"]), k["zadavatelu"],
                     k["top_segment"]] for i, k in enumerate(an["konkurenti"][:20])]))
    L.append("\n*Win rate = výhry / známé účasti; počítá se jen tam, kde data uvádějí účastníky. "
             "„Cena vs. odhad“ = medián poměru vítězné ceny k předpokládané hodnotě.*")
    if an["rs_top"]:
        L.append("\n**Registr smluv – největší protistrany v oboru (kontrola z druhého zdroje):**")
        L.append(table(["Dodavatel", "IČO", "Smluv", "Hodnota bez DPH"],
                       [[r["nazev"], r["ico"], r["n"], kc(r["h"])] for r in an["rs_top"][:10]]))
    L.append("")

    L.append("## KIQ 3: Typické podmínky v segmentu")
    L.append(f"- Předpokládaná hodnota: medián {kc(k3['median_hodnota'])}, typické pásmo {kc(k3['p25'])} – {kc(k3['p75'])}.")
    if k3["prumer_nabidek"]:
        L.append(f"- Průměrně {str(round(k3['prumer_nabidek'], 1)).replace('.', ',')} nabídky na zakázku; jediná nabídka u {k3['jedna_nabidka']} z {k3['s_poctem']}.")
    if k3["s_kriterii"]:
        L.append(f"- Hodnoticí kritéria (u {k3['s_kriterii']} zakázek): " +
                 ", ".join(f"{k} {n}×" for k, n in k3["kriteria"]) + f"; jen cena u {k3['jen_cena']}.")
    L.append("- Druhy řízení: " + ", ".join(f"{k} ({n})" for k, n in k3["postupy"]))
    L.append("")

    L.append("## KIQ 5: Naše pozice")
    k5 = an["kiq5"]
    if not k5:
        L.append("Není vyplněno `nase_ico` v config.json – doplňte IČO vaší firmy a analýza ukáže win rate, cenovou hladinu "
                 "a silné segmenty proti trhu.")
    elif not k5["data"]:
        L.append(f"{k5['firma']}: v období nemáme v datech žádnou výhru ani účast.")
    else:
        d = k5["data"]
        L.append(f"- **{k5['firma']}**: {d['vyhry']} výher, objem {kc(d['objem'])}, {k5['poradi']}. místo z {k5['konkurentu']} dodavatelů.")
        L.append(f"- Win rate: {pct(d['win_rate'])}; cena vs. odhad {pct(d['median_pomer'])} (trh {pct(k5['trh_median_pomer'])}).")
        L.append(f"- Nejsilnější segment: {d['top_segment']}; zákazníků (zadavatelů): {d['zadavatelu']}.")
    L.append("")

    if zpravy:
        L.append("## Kontext: zprávy")
        for z in zpravy[:12]:
            L.append(f"- {z['datum'] or ''} [{z['titulek']}]({z['url']}) – *{z['dotaz']}*")
        L.append("")

    L.append("## Zdroje a běh agentů")
    for k, v in run_stats.items():
        L.append(f"- **{k}**: {v}")
    L.append("\n*Zdroje: Registr veřejných zakázek / NEN / Věstník (open data ISVZ, MMR), Registr smluv (data.smlouvy.gov.cz), "
             "ARES (MF ČR), Hlídač státu (volitelně), Google News RSS. Data zpracována automaticky – před rozhodnutím ověřte "
             "detail zakázky u zdroje.*")
    return "\n".join(L)


# ---- jednoduchy Markdown -> HTML (bez externich knihoven) ----
def _inline(s):
    s = html.escape(s, quote=False)
    s = re.sub(r"\[([^\]]+)\]\((https?://[^)\s]+)\)", r'<a href="\2">\1</a>', s)
    s = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", s)
    s = re.sub(r"(?<!\*)\*(?!\s)(.+?)(?<!\s)\*(?!\*)", r"<i>\1</i>", s)
    s = re.sub(r"`(.+?)`", r"<code>\1</code>", s)
    return s


def md_to_html(md, title):
    out, in_list, in_table = [], False, False
    for line in md.split("\n"):
        if line.startswith("|"):
            cells = [c.strip() for c in line.strip("|").split("|")]
            if all(set(c) <= set("-") for c in cells):
                continue
            if not in_table:
                out.append("<table>")
                in_table = True
                out.append("<tr>" + "".join(f"<th>{_inline(c)}</th>" for c in cells) + "</tr>")
            else:
                out.append("<tr>" + "".join(f"<td>{_inline(c)}</td>" for c in cells) + "</tr>")
            continue
        if in_table:
            out.append("</table>")
            in_table = False
        if line.startswith("- "):
            if not in_list:
                out.append("<ul>")
                in_list = True
            out.append(f"<li>{_inline(line[2:])}</li>")
            continue
        if in_list:
            out.append("</ul>")
            in_list = False
        if line.startswith("# "):
            out.append(f"<h1>{_inline(line[2:])}</h1>")
        elif line.startswith("## "):
            out.append(f"<h2>{_inline(line[3:])}</h2>")
        elif line.strip():
            out.append(f"<p>{_inline(line)}</p>")
    if in_list:
        out.append("</ul>")
    if in_table:
        out.append("</table>")
    css = ("body{font-family:Segoe UI,Arial,sans-serif;max-width:1200px;margin:24px auto;padding:0 16px;color:#1d2433}"
           "h1{border-bottom:3px solid #2457a6;padding-bottom:6px}h2{color:#2457a6;margin-top:32px}"
           "table{border-collapse:collapse;width:100%;font-size:13px;margin:8px 0}th,td{border:1px solid #d5dae3;padding:5px 7px;"
           "vertical-align:top;text-align:left}th{background:#eef2f9}tr:nth-child(even) td{background:#fafbfd}"
           "a{color:#2457a6}code{background:#f1f3f7;padding:1px 4px}")
    return (f"<!doctype html><html lang='cs'><head><meta charset='utf-8'><title>{html.escape(title)}</title>"
            f"<style>{css}</style></head><body>{''.join(out)}</body></html>")


def save(md, approved, suffix=""):
    d = date.today().isoformat()
    stem = f"brief_{d}{suffix}" + ("" if approved else "_NAVRH")
    p_md = os.path.join(OUT_DIR, stem + ".md")
    p_html = os.path.join(OUT_DIR, stem + ".html")
    with open(p_md, "w", encoding="utf-8") as f:
        f.write(md)
    with open(p_html, "w", encoding="utf-8") as f:
        f.write(md_to_html(md, "TenderScope brief " + d))
    log(A, f"brief ulozen: {p_html}")
    return p_md, p_html
