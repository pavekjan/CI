"""Limity AI poskytovatelu: zname hodnoty z dokumentace, zivy stav z API a hlavicek, pauzy po 429/402.

Kazdy poskytovatel ma vlastni limity (dotazy za minutu / den, tokeny). Aplikace:
- pred volanim zkontroluje, jestli by limit neprekrocila (pocita si volani sama) -> radsi pravidla nez chyba,
- z odpovedi cte hlavicky x-ratelimit-* / anthropic-ratelimit-* / retry-after (kolik zbyva),
- u OpenRouteru umi zjistit zbyvajici denni pocet zivě (GET /api/v1/key -> free_model_daily_requests),
- po 429 nebo 402 pocka (kratce, s exponencialnim odstupem) nebo poskytovatele docasne vynecha
  a onboarding mezitim jede na pravidla.

Hodnoty limitu a zdroje (overeno 2026-11-13):
- OpenRouter, modely zdarma (":free", openrouter/free): 20/min; 50/den, 1000/den po nakupu aspon 10 kreditu
  https://openrouter.ai/docs/api_reference/limits
- Groq (openai/gpt-oss-120b, bezplatna uroven): 30/min, 1 000/den, 8 000 tokenu/min, 200 000 tokenu/den
  https://console.groq.com/docs/rate-limits
- Cohere zkusebni klic: 20/min (chat), 1 000 volani/mesic  https://docs.cohere.com/docs/rate-limits
- Cloudflare Workers AI: 10 000 neuronu/den zdarma, reset 00:00 UTC
  https://developers.cloudflare.com/workers-ai/platform/pricing/
- OpenAI, Anthropic, Mistral, Google Gemini: limity podle urovne uctu/projektu -> ctou se z hlavicek odpovedi
  https://platform.openai.com/docs/guides/rate-limits, https://docs.anthropic.com/en/api/rate-limits,
  https://ai.google.dev/gemini-api/docs/rate-limits
- ostatni bezplatne (Z AI, NVIDIA, Gonka, OVH, Kilo, LLM7): podle https://github.com/mnfst/awesome-free-llm-apis
"""
import re
import threading
import time
from collections import deque
from datetime import datetime, timezone

OR_DOC = "https://openrouter.ai/docs/api_reference/limits"
LIMITY = {
    "openrouter_free": {"rpm": 20, "rpd": 50, "pozn": "50 dotazů/den, po nákupu aspoň 10 kreditů 1 000/den", "zdroj": OR_DOC},
    "groq": {"rpm": 30, "rpd": 1000, "tpm": 8000, "tpd": 200000, "pozn": "platí pro openai/gpt-oss-120b",
             "zdroj": "https://console.groq.com/docs/rate-limits"},
    "cohere": {"rpm": 20, "mesicne": 1000, "zdroj": "https://docs.cohere.com/docs/rate-limits"},
    "cloudflare": {"pozn": "10 000 „neuronů“ denně (podle velikosti dotazu), reset 00:00 UTC",
                   "zdroj": "https://developers.cloudflare.com/workers-ai/platform/pricing/"},
    "openrouter": {"pozn": "placené modely bez limitu počtu dotazů, hlídá se kredit (chyba 402)", "zdroj": OR_DOC},
    "openai": {"pozn": "podle úrovně účtu (tier), zbývající počet se čte z odpovědí",
               "zdroj": "https://platform.openai.com/docs/guides/rate-limits"},
    "anthropic": {"pozn": "podle úrovně účtu (tier), měsíční strop útraty", "zdroj": "https://docs.anthropic.com/en/api/rate-limits"},
    "mistral": {"pozn": "podle úrovně účtu, zbývající počet se čte z odpovědí", "zdroj": "https://docs.mistral.ai/"},
    "gemini": {"pozn": "podle projektu v Google AI Studiu, zbývající počet se čte z odpovědí",
               "zdroj": "https://ai.google.dev/gemini-api/docs/rate-limits"},
    "zai": {"soubezne": 1, "pozn": "modely *-Flash zdarma, 1 souběžný dotaz", "zdroj": "https://github.com/mnfst/awesome-free-llm-apis"},
    "ovh": {"rpm": 2, "pozn": "bez klíče 2 dotazy/min na model a IP adresu", "zdroj": "https://github.com/mnfst/awesome-free-llm-apis"},
    "kilo": {"rph": 200, "zdroj": "https://github.com/mnfst/awesome-free-llm-apis"},
    "llm7": {"rpm": 60, "rph": 250, "pozn": "s bezplatným tokenem", "zdroj": "https://github.com/mnfst/awesome-free-llm-apis"},
    "nvidia": {"pozn": "podle modelu", "zdroj": "https://github.com/mnfst/awesome-free-llm-apis"},
    "gonka": {"pozn": "cca 1 mil. tokenů měsíčně", "zdroj": "https://github.com/mnfst/awesome-free-llm-apis"},
    "ollama": {"pozn": "bez limitu"},
}
MAX_CEKANI = 20  # s - dele uzivatel v onboardingu cekat nema, radsi pravidla


def je_free_model(n):
    m = (n.get("model") or "").lower()
    return m.endswith(":free") or m == "openrouter/free"


def klic_limitu(n):
    """OpenRouter s modelem zdarma ma limity jako predvolba "modely zdarma"."""
    if n["prov"] in ("openrouter", "openrouter_free") and je_free_model(n):
        return "openrouter_free"
    return n["prov"]


def limity(n):
    return LIMITY.get(klic_limitu(n), {})


class _Stav:
    def __init__(self):
        self.volani = deque()          # casy volani (max 31 dni)
        self.pauza_do = 0.0
        self.pauza_duvod = ""
        self.hlavicky = {}             # posledni zname hodnoty z hlavicek
        self.hlavicky_cas = None
        self.zivy = None               # OpenRouter /key
        self.zivy_cas = 0.0


_STAV = {}
_ZAMEK = threading.Lock()


def _st(n):
    with _ZAMEK:
        return _STAV.setdefault(klic_limitu(n) + "|" + (n.get("klic") or "")[-6:], _Stav())


def _pocet(st, sekund, ted):
    return sum(1 for t in st.volani if t >= ted - sekund)


def _od_pulnoci_utc(ted):
    d = datetime.fromtimestamp(ted, timezone.utc)
    return d.hour * 3600 + d.minute * 60 + d.second


def pred_volanim(n):
    """Vrati None (muze se volat), nebo duvod, proc ted ne. Pri volnu volani rovnou zapocita."""
    lim, st, ted = limity(n), _st(n), time.time()
    with _ZAMEK:
        while st.volani and st.volani[0] < ted - 31 * 86400:
            st.volani.popleft()
        if st.pauza_do > ted:
            zb = int(st.pauza_do - ted)
            return f"{st.pauza_duvod or 'limit poskytovatele vyčerpán'} – AI znovu zkusím za {_trvani(zb)}"
        kontroly = (("rpm", 60, "za minutu"), ("rph", 3600, "za hodinu"), ("rpd", _od_pulnoci_utc(ted), "za den"),
                    ("mesicne", 30 * 86400, "za měsíc"))
        for k, okno, txt in kontroly:
            mx = lim.get(k)
            if k == "rpd" and st.zivy and st.zivy.get("denni_limit"):
                mx = st.zivy["denni_limit"]
            if mx and _pocet(st, okno, ted) >= mx:
                return f"vyčerpán limit poskytovatele {mx} dotazů {txt}"
        zbyva = st.hlavicky.get("zbyva_dotazu")
        if zbyva is not None and zbyva <= 0 and st.hlavicky.get("reset_s"):
            if (st.hlavicky_cas or 0) + st.hlavicky["reset_s"] > ted:
                return "poskytovatel hlásí 0 zbývajících dotazů"
        st.volani.append(ted)
    return None


def _trvani(s):
    s = max(1, int(s))
    return f"{s} s" if s < 90 else f"{round(s / 60)} min" if s < 5400 else f"{round(s / 3600)} h"


def _cas_hlavicky(v):
    """'2m59.56s' / '7.66s' / '2' / epoch v ms -> sekundy."""
    if v is None:
        return None
    v = str(v).strip()
    if re.fullmatch(r"\d{12,}", v):           # epoch v milisekundach (OpenRouter X-RateLimit-Reset)
        return max(0.0, int(v) / 1000 - time.time())
    if re.fullmatch(r"\d+(\.\d+)?", v):
        return float(v)
    m = re.fullmatch(r"(?:(\d+)h)?(?:(\d+)m(?!s))?(?:([\d.]+)s)?(?:(\d+)ms)?", v)
    if m and any(m.groups()):
        h, mi, s, ms = m.groups()
        return int(h or 0) * 3600 + int(mi or 0) * 60 + float(s or 0) + int(ms or 0) / 1000
    try:  # ISO cas (Anthropic)
        return max(0.0, datetime.fromisoformat(v.replace("Z", "+00:00")).timestamp() - time.time())
    except ValueError:
        return None


def _int(v):
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return None


def po_odpovedi(n, hlavicky):
    """Ulozi, kolik podle poskytovatele zbyva (hlavicky x-ratelimit-*, anthropic-ratelimit-*)."""
    h = {k.lower(): v for k, v in (hlavicky or {}).items()}
    zbyva = _int(h.get("x-ratelimit-remaining-requests") or h.get("anthropic-ratelimit-requests-remaining")
                 or h.get("x-ratelimit-remaining"))
    limit = _int(h.get("x-ratelimit-limit-requests") or h.get("anthropic-ratelimit-requests-limit") or h.get("x-ratelimit-limit"))
    reset = _cas_hlavicky(h.get("x-ratelimit-reset-requests") or h.get("anthropic-ratelimit-requests-reset")
                          or h.get("x-ratelimit-reset"))
    tok = _int(h.get("x-ratelimit-remaining-tokens") or h.get("anthropic-ratelimit-tokens-remaining"))
    if zbyva is None and tok is None:
        return
    st = _st(n)
    with _ZAMEK:
        st.hlavicky = {"zbyva_dotazu": zbyva, "limit_dotazu": limit, "reset_s": reset, "zbyva_tokenu": tok}
        st.hlavicky_cas = time.time()


def po_chybe(n, status, hlavicky, telo_text, pokus):
    """Po 429/402/503: vrati pocet sekund, kolik pockat a zkusit znovu, nebo None (vzdat to -> pravidla).
    Dlouhe cekani (denni limit, dosly kredit) ulozi jako pauzu, aby se poskytovatel zbytecne nevolal."""
    h = {k.lower(): v for k, v in (hlavicky or {}).items()}
    t = (telo_text or "").lower()
    retry = _cas_hlavicky(h.get("retry-after"))
    reset = _cas_hlavicky(h.get("x-ratelimit-reset"))
    po_odpovedi(n, hlavicky)
    st = _st(n)
    if status == 402:
        if "in_flight" in t and retry is not None and retry <= MAX_CEKANI and pokus < 2:
            return retry
        duvod, cekat = "došel kredit nebo je vyčerpaný limit klíče (402)", 3600
    elif status == 429:
        denni = (any(w in t for w in ("per day", "per-day", "daily", "free-models-per-day", "/day", "rpd"))
                 or (reset is not None and reset > 120))
        if not denni:
            cekat = retry if retry is not None else min(MAX_CEKANI, 2 * 2 ** pokus)   # exponencialni odstup 2, 4, 8 s
            if cekat <= MAX_CEKANI and pokus < 3:
                return cekat
            duvod = "příliš mnoho dotazů za minutu (429)"
        else:
            duvod = "vyčerpán denní limit poskytovatele (429)"
            cekat = reset if reset else _do_pulnoci_utc()
    elif status in (500, 502, 503, 529):
        return 2 * 2 ** pokus if pokus < 2 else None
    else:
        return None
    with _ZAMEK:
        st.pauza_do = time.time() + max(30, cekat)
        st.pauza_duvod = duvod
    return None


def _do_pulnoci_utc():
    return 86400 - _od_pulnoci_utc(time.time())


def zivy_stav(n, session_get):
    """OpenRouter: GET /api/v1/key (nic nestoji, zvlastni limit na IP) -> denni pocet dotazu zdarma a kredit.
    Vysledek se 60 s drzi v pameti."""
    if n["prov"] not in ("openrouter", "openrouter_free") or not n.get("klic"):
        return None
    st = _st(n)
    if st.zivy and time.time() - st.zivy_cas < 60:
        return st.zivy
    try:
        r = session_get("https://openrouter.ai/api/v1/key", headers={"Authorization": f"Bearer {n['klic']}"},
                        timeout=15, allow_redirects=False)
        if r.status_code != 200:
            return st.zivy
        d = (r.json() or {}).get("data") or {}
    except Exception:
        return st.zivy
    f = d.get("free_model_daily_requests") or {}
    zivy = {"denni_limit": _int(f.get("limit")), "denni_pouzito": _int(f.get("used")), "denni_zbyva": _int(f.get("remaining")),
            "kredit_zbyva": d.get("limit_remaining"), "zdarma_uroven": d.get("is_free_tier")}
    with _ZAMEK:
        st.zivy, st.zivy_cas = zivy, time.time()
        if zivy["denni_zbyva"] == 0 and je_free_model(n):
            st.pauza_do, st.pauza_duvod = time.time() + _do_pulnoci_utc(), "vyčerpán denní limit dotazů zdarma"
    return zivy


def stav(n):
    """Pro stranku Data: limity z dokumentace, kolik volani dnes/za minutu, zivy stav a pripadna pauza."""
    lim, st, ted = limity(n), _st(n), time.time()
    with _ZAMEK:
        out = {"poskytovatel": n["nazev"], "model": n["model"], "limity": lim,
               "za_minutu": _pocet(st, 60, ted), "dnes": _pocet(st, _od_pulnoci_utc(ted), ted),
               "za_mesic": _pocet(st, 30 * 86400, ted),
               "pauza": ({"duvod": st.pauza_duvod, "zbyva": _trvani(st.pauza_do - ted)} if st.pauza_do > ted else None),
               "hlavicky": dict(st.hlavicky) if st.hlavicky else None, "zivy": dict(st.zivy) if st.zivy else None}
    return out


def reset_pro_testy():
    with _ZAMEK:
        _STAV.clear()
