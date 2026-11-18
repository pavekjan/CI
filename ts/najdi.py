"""Najdi firmu podle IČO, nazvu nebo webu (start onboardingu).

Poradi:
  1. vstup jsou jen cislice      -> IČO (overeny kontrolni soucet)
  2. vstup vypada jako web/domena -> stahne se titulni stranka (+ kontakt), z ni IČO (pravni povinnost
                                    uvadet ho na webu podnikatele, § 435 obc. zakoniku); kdyz neni, hleda se podle domeny
  3. jinak nazev                  -> lokalni rejstrik dodavatelu + ARES (vyhledani podle obchodniho jmena)

Vsechny site jdou pres bezpecnost.stahni_web (jen verejne adresy, kontrola presmerovani, max. 1 MB).
Obsah webu je jen data: berou se z nej pouze osmimistna cisla s platnym kontrolnim souctem.
"""
import re
from urllib.parse import urljoin, urlparse

from .util import clean_ico, norm

# "IČ: 123 45 678", "IČO 12345678", "ICO:12345678", "Identifikační číslo: ..."
ICO_NA_WEBU = re.compile(r"(?:I\s*Č\s*O?|I\s*C\s*O?|IČ\s*:|identifika[čc]n[íi]\s+[čc][íi]slo)\s*[:.]?\s*((?:\d\s?){8})(?!\d)", re.I)
KONTAKT = re.compile(r"""href=["']([^"'#]*(?:kontakt|contact|o-nas|about|impressum|firma)[^"'#]*)["']""", re.I)
DOMENA = re.compile(r"^(https?://)?([a-z0-9-]+\.)+[a-z]{2,}(/.*)?$", re.I)
PRAVNI = {"sro", "spol", "as", "a", "s", "r", "o", "vos", "ks", "se", "zs", "cz", "www", "eu", "com", "group"}


def ico_platne(ico):
    """Kontrolni soucet IČO (modulo 11), aby se z webu nevzalo nahodne cislo (telefon, ucet...)."""
    if not ico or not re.fullmatch(r"\d{8}", ico):
        return False
    s = sum(int(ico[i]) * (8 - i) for i in range(7))
    c = (11 - s % 11) % 10
    return c == int(ico[7])


def je_web(q):
    q = (q or "").strip()
    return bool(q) and " " not in q and bool(DOMENA.match(q)) and not re.fullmatch(r"[\d.\s]+", q)


def ica_z_html(html):
    """Platna IČO nalezena v textu stranky, v poradi vyskytu (bez duplicit)."""
    text = re.sub(r"(?s)<[^>]+>", " ", html or "")
    text = re.sub(r"&nbsp;|&#160;|\xa0", " ", text)
    out = []
    for m in ICO_NA_WEBU.finditer(text):
        ico = re.sub(r"\D", "", m.group(1))
        if ico_platne(ico) and ico not in out:
            out.append(ico)
    return out


def _stahni(url):
    from . import bezpecnost
    from .util import session
    status, html, url = bezpecnost.stahni_web(url, session(), max_bajtu=600_000, timeout=8)
    return (html if status == 200 else ""), url


def ica_z_webu(url, max_podstranek=2):
    """(seznam IČO, finalni URL, titulek). Nejdriv titulni stranka, pak az 2 odkazy typu Kontakt / O nas."""
    html, final = _stahni(url)
    titulek = re.search(r"<title[^>]*>(.*?)</title>", html, re.S | re.I)
    titulek = re.sub(r"\s+", " ", titulek.group(1)).strip()[:150] if titulek else None
    ica = ica_z_html(html)
    if not ica:
        host = urlparse(final).hostname
        videno = set()
        for href in KONTAKT.findall(html):
            dalsi = urljoin(final, href)
            if urlparse(dalsi).hostname != host or dalsi in videno:
                continue  # jen stejny web, ne odkazy jinam
            videno.add(dalsi)
            try:
                ica = ica_z_html(_stahni(dalsi)[0])
            except Exception:
                ica = []
            if ica or len(videno) >= max_podstranek:
                break
    return ica, final, titulek


def kmen_domeny(url):
    """https://www.alza.cz/kontakt -> 'alza'; 'stavby-novak.cz' -> 'stavby novak'."""
    host = (urlparse(url if "://" in url else "https://" + url).hostname or "").lower()
    casti = [c for c in host.split(".") if c not in ("www", "")]
    return (casti[-2] if len(casti) >= 2 else (casti[0] if casti else "")).replace("-", " ")


def _skore_shody(dotaz, nazev):
    """Jak dobre nazev odpovida dotazu (0-1): shoda slov bez pravni formy."""
    a = [w for w in norm(dotaz).split() if w not in PRAVNI]
    b = [w for w in norm(nazev or "").split() if w not in PRAVNI]
    if not a or not b:
        return 0.0
    hit = sum(1 for w in a if any(x.startswith(w) for x in b))
    zacatek = 0.2 if b[0].startswith(a[0]) else 0.0
    return min(1.0, hit / len(a) * 0.8 + zacatek)


def najdi(con, q, ares_base=None, online=True):
    """Vraci {"dotaz", "typ": ico|web|nazev, "web": URL nebo None, "kandidati": [...], "poznamka"}."""
    from .api import ares_hledat
    q = (q or "").strip()
    out = {"dotaz": q, "typ": "nazev", "web": None, "kandidati": [], "poznamka": None}
    if not q:
        return out

    def lokalne(ico):
        r = con.execute("SELECT ico, nazev, vyhry, ucasti, objem, smluv_rs FROM dodavatele WHERE ico=?", (ico,)).fetchone()
        return dict(r) if r else None

    def pridej(ico, nazev=None, zdroj="", sidlo=None, shoda=None):
        if not ico or any(k["ico"] == ico for k in out["kandidati"]):
            return
        lok = lokalne(ico) or {}
        f = con.execute("SELECT nazev, sidlo FROM firmy WHERE ico=?", (ico,)).fetchone()
        out["kandidati"].append({
            "ico": ico, "nazev": nazev or lok.get("nazev") or (f["nazev"] if f else None),
            "sidlo": sidlo or (f["sidlo"] if f else None), "zdroj": zdroj,
            "vyhry": lok.get("vyhry") or 0, "ucasti": lok.get("ucasti") or 0, "objem": lok.get("objem") or 0,
            "smluv_rs": lok.get("smluv_rs") or 0, "shoda": shoda})

    cislice = re.sub(r"\s", "", q)
    if re.fullmatch(r"\d{1,8}", cislice):
        out["typ"] = "ico"
        ico = clean_ico(cislice)
        if not ico_platne(ico):
            out["poznamka"] = "Toto IČO nemá platný kontrolní součet – zkontrolujte, zda je opsané správně."
        pridej(ico, zdroj="IČO")
        if ares_base and online and not out["kandidati"][0]["nazev"]:
            for f in ares_hledat(ares_base, None, ico=ico):
                out["kandidati"][0].update({"nazev": f["nazev"], "sidlo": f.get("sidlo"), "zdroj": "ARES"})
        return out

    hledany_nazev = q
    if je_web(q):
        out["typ"] = "web"
        if online:
            try:
                ica, final, titulek = ica_z_webu(q)
                out["web"] = final
                for ico in ica[:3]:
                    pridej(ico, zdroj="IČO uvedené na webu")
                if ica and ares_base:
                    for k in out["kandidati"]:
                        if not k["nazev"]:
                            for f in ares_hledat(ares_base, None, ico=k["ico"]):
                                k.update({"nazev": f["nazev"], "sidlo": k["sidlo"] or f.get("sidlo")})
                if not ica:
                    out["poznamka"] = "Na webu jsem IČO nenašel, hledám podle názvu domény – vyberte správnou firmu."
            except Exception as e:  # nedostupny web: pokracovat hledanim podle domeny
                out["web"] = None  # nedostupny web nema smysl predavat do reserse
                out["poznamka"] = f"Web se nepodařilo načíst ({str(e)[:80] or type(e).__name__}), hledám podle názvu domény."
        else:
            out["web"] = q if "://" in q else "https://" + q
        if out["kandidati"]:
            return out
        hledany_nazev = kmen_domeny(q)

    # nazev: lokalni rejstrik (firmy s historii ve verejnych zakazkach) + ARES (vsechny firmy v CR)
    slova = [w for w in norm(hledany_nazev).split() if w not in PRAVNI] or norm(hledany_nazev).split()
    if slova:
        where = " AND ".join("nazev_norm LIKE ?" for _ in slova)
        # bezpecnost: jen zastupne znaky ?, hodnoty jdou jako parametry
        rows = con.execute(f"SELECT ico, nazev FROM dodavatele WHERE {where} ORDER BY objem DESC, smluv_rs DESC LIMIT 8",  # nosec B608
                           [f"%{w}%" for w in slova]).fetchall()
        for r in rows:
            pridej(r["ico"], r["nazev"], "databáze zakázek", shoda=_skore_shody(hledany_nazev, r["nazev"]))
    if ares_base and online:
        for f in ares_hledat(ares_base, hledany_nazev, pocet=8):
            if f.get("ico"):
                pridej(clean_ico(f["ico"]), f["nazev"], "ARES", f.get("sidlo"), shoda=_skore_shody(hledany_nazev, f["nazev"]))
    # nejlepsi shoda nahoru, pri shode vic historie ve verejnych zakazkach
    out["kandidati"].sort(key=lambda k: (-(k["shoda"] or 0), -(k["objem"] or 0), -(k["smluv_rs"] or 0)))
    out["kandidati"] = out["kandidati"][:8]
    if not out["kandidati"]:
        out["poznamka"] = ((out["poznamka"] or "") + " Nic jsem nenašel – zkuste přesnější název nebo IČO.").strip()
    return out
