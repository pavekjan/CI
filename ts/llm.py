"""Volani jazykoveho modelu (AI) pro Onboarding agenta. Poskytovatele jde vybrat v aplikaci (Data -> Umela inteligence).

Podporovani poskytovatele:
- Anthropic Claude (oficialni SDK `anthropic`)
- OpenAI, Google Gemini, Mistral, OpenRouter, Ollama (lokalne) a libovolne OpenAI-kompatibilni API
  (vse pres standardni endpoint /chat/completions a knihovnu `requests`, zadny dalsi balicek)

Bez klice nebo pri chybe se pouzije pravidlovy zaloznik v onboarding.py, takze aplikace funguje vzdy.
Bezpecnost: klice jen z promennych prostredi / config.local.json, nikdy do logu ani do odpovedi;
vystup modelu je nedueryhodny a vzdy se validuje (onboarding._ocisti_*).
"""
import json
import time
import os
import re

from . import ai_limity
from .util import log, session

A = "LLM"
DEFAULT_MODEL = "claude-opus-5-5"
PROMPT_PATH = os.path.join(os.path.dirname(__file__), "prompty", "onboarding_system.md")

# Nazvy modelu se meni. Vychozi hodnoty jsou jen navrh, v aplikaci jde nacist aktualni seznam ("Načíst modely").
# Bezplatne predvolby a jejich adresy/limity jsou overene podle https://github.com/mnfst/awesome-free-llm-apis
# (data.json, aktualizace 2026-11-11). Vynechani: ModelScope a SiliconFlow (vyzaduji cinske overeni totoznosti),
# Aion Labs (zamereny na roleplay).
_LOG = "Bezplatné tarify mohou dotazy ukládat nebo je použít ke zlepšování modelů."
POSKYTOVATELE = {
    # ---------------------------------------------------------------- placene (podle spotreby)
    "anthropic": {"nazev": "Anthropic Claude", "typ": "anthropic", "klic": "anthropic_api_key", "env": "ANTHROPIC_API_KEY",
                  "model": DEFAULT_MODEL, "url": "", "web": "https://console.anthropic.com"},
    "openai": {"nazev": "OpenAI (ChatGPT)", "typ": "openai", "klic": "openai_api_key", "env": "OPENAI_API_KEY",
               "model": "gpt-5", "url": "https://api.openai.com/v1", "web": "https://platform.openai.com/api-keys"},
    "mistral": {"nazev": "Mistral AI", "typ": "openai", "klic": "mistral_api_key", "env": "MISTRAL_API_KEY",
                "model": "mistral-large-latest", "url": "https://api.mistral.ai/v1", "web": "https://console.mistral.ai/api-keys"},
    "openrouter": {"nazev": "OpenRouter (stovky modelů)", "typ": "openai", "klic": "openrouter_api_key", "env": "OPENROUTER_API_KEY",
                   "model": "openrouter/auto", "url": "https://openrouter.ai/api/v1", "web": "https://openrouter.ai/keys"},
    # ---------------------------------------------------------------- zdarma
    "gemini": {"nazev": "Google Gemini", "typ": "openai", "klic": "gemini_api_key", "env": "GEMINI_API_KEY", "zdarma": True,
               "model": "gemini-2.5-flash", "url": "https://generativelanguage.googleapis.com/v1beta/openai",
               "web": "https://aistudio.google.com/app/apikey",
               "limit": "bezplatná úroveň bez karty, limity podle účtu v AI Studiu",
               "pozn": "V EU se dotazy z bezplatné úrovně nepoužívají k tréninku. Podmínky ale pro aplikace "
                       "zpřístupněné uživatelům v EU vyžadují placenou úroveň: pro vlastní a školní použití OK, "
                       "na veřejné online verzi raději placený klíč."},
    "groq": {"nazev": "Groq", "typ": "openai", "klic": "groq_api_key", "env": "GROQ_API_KEY", "zdarma": True,
             "model": "openai/gpt-oss-120b", "url": "https://api.groq.com/openai/v1", "web": "https://console.groq.com/keys",
             "limit": "30 dotazů/min, 1 000/den, 8 000 tokenů/min", "pozn": "Velmi rychlé. Bez platební karty."},
    "openrouter_free": {"nazev": "OpenRouter – modely zdarma", "typ": "openai", "klic": "openrouter_api_key",
                        "env": "OPENROUTER_API_KEY", "zdarma": True, "model": "openrouter/free",
                        "url": "https://openrouter.ai/api/v1", "web": "https://openrouter.ai/keys",
                        "limit": "20 dotazů/min, 50/den (modely s koncovkou :free)",
                        "pozn": "openrouter/free sám vybere volný model. Poskytovatelé zdarma mohou dotazy logovat k tréninku."},
    "cloudflare": {"nazev": "Cloudflare Workers AI", "typ": "openai", "klic": "cloudflare_api_key", "env": "CLOUDFLARE_API_TOKEN",
                   "zdarma": True, "model": "@cf/openai/gpt-oss-120b",
                   "url": "https://api.cloudflare.com/client/v4/accounts/{account_id}/ai/v1", "ucet": True,
                   "web": "https://dash.cloudflare.com/profile/api-tokens",
                   "limit": "10 000 „neuronů“ denně (sdílené), po vyčerpání dotaz selže, nic se neúčtuje",
                   "pozn": "Potřebuje API token (oprávnění Workers AI) a Account ID z přehledu účtu Cloudflare."},
    "cohere": {"nazev": "Cohere", "typ": "openai", "klic": "cohere_api_key", "env": "COHERE_API_KEY", "zdarma": True,
               "model": "command-a-03-2025", "url": "https://api.cohere.ai/compatibility/v1",
               "web": "https://dashboard.cohere.com/api-keys",
               "limit": "zkušební klíč: 1 000 volání/měsíc, 20/min", "pozn": "Zkušební klíč jen pro nekomerční použití (školní projekt OK)."},
    "zai": {"nazev": "Z AI (GLM)", "typ": "openai", "klic": "zai_api_key", "env": "ZAI_API_KEY", "zdarma": True,
            "model": "glm-4.7-flash", "url": "https://api.z.ai/api/paas/v4", "web": "https://z.ai",
            "limit": "modely *-Flash zdarma, 1 souběžný dotaz",
            "pozn": "Mezinárodní platforma čínské firmy Zhipu AI. Data odcházejí mimo EU."},
    "nvidia": {"nazev": "NVIDIA NIM", "typ": "openai", "klic": "nvidia_api_key", "env": "NVIDIA_API_KEY", "zdarma": True,
               "model": "google/gemma-4-31b-it", "url": "https://integrate.api.nvidia.com/v1",
               "web": "https://build.nvidia.com/explore/discover",
               "limit": "zdarma s členstvím v NVIDIA Developer Program, limity podle modelu",
               "pozn": "Jen pro vývoj, výzkum a testování (školní projekt OK), ne pro ostrý provoz."},
    "gonka": {"nazev": "Gonka Broker", "typ": "openai", "klic": "gonka_api_key", "env": "GONKA_API_KEY", "zdarma": True,
              "model": "deepseek-ai/DeepSeek-V4-Flash-0731", "url": "https://proxy.gonkabroker.com/v1",
              "web": "https://app.gonkabroker.com/signup",
              "limit": "cca 1 mil. tokenů měsíčně", "pozn": "Bezplatný kredit až po ověření skutečným telefonním číslem (SMS)."},
    "ovh": {"nazev": "OVHcloud AI Endpoints (EU)", "typ": "openai", "klic": "ovh_api_key", "env": "OVH_API_KEY",
            "zdarma": True, "klic_volitelny": True, "model": "gpt-oss-120b",
            "url": "https://oai.endpoints.kepler.ai.cloud.ovh.net/v1",
            "web": "https://www.ovhcloud.com/en/public-cloud/ai-endpoints/catalog/",
            "limit": "bez klíče 2 dotazy/min na model a IP adresu",
            "pozn": "Francouzská firma, modely běží v datacentrech v EU. Klíč není potřeba (s klíčem je to placené)."},
    "kilo": {"nazev": "Kilo Code", "typ": "openai", "klic": "kilo_api_key", "env": "KILO_API_KEY",
             "zdarma": True, "klic_volitelny": True, "model": "kilo-auto/free", "url": "https://api.kilo.ai/api/gateway",
             "web": "https://app.kilo.ai/profile", "limit": "200 dotazů/hod na IP adresu",
             "pozn": "kilo-auto/free vybírá z volných modelů a podle Kilo může posílat dotazy poskytovatelům, kteří je logují."},
    "llm7": {"nazev": "LLM7.io", "typ": "openai", "klic": "llm7_api_key", "env": "LLM7_API_KEY",
             "zdarma": True, "klic_volitelny": True, "model": "gpt-oss:20b", "url": "https://api.llm7.io/v1",
             "web": "https://token.llm7.io", "limit": "bezplatný token: 60 dotazů/min, 250/hod",
             "pozn": "Funguje i bez klíče, bezplatný token z token.llm7.io zvedne limity. Nabídka modelů se často mění."},
    # ---------------------------------------------------------------- lokalne / vlastni
    "ollama": {"nazev": "Ollama (na vašem počítači)", "typ": "openai", "klic": None, "env": None, "zdarma": True,
               "model": "llama3.1", "url": "http://localhost:11434/v1", "web": "https://ollama.com", "vlastni_url": True,
               "limit": "bez limitu, podle výkonu počítače", "pozn": "Data nikam neodcházejí. Na online verzi nefunguje.",
               "soukromi_ok": True},
    "vlastni": {"nazev": "Vlastní (OpenAI-kompatibilní API)", "typ": "openai", "klic": "vlastni_api_key", "env": "LLM_API_KEY",
                "model": "", "url": "", "web": "", "vlastni_url": True, "klic_volitelny": True},
}
KLICE = tuple(sorted({p["klic"] for p in POSKYTOVATELE.values() if p["klic"]}))
UCET_RE = r"[0-9a-f]{32}"


def env_do_cfg(cfg):
    """Klice a nastaveni AI z promennych prostredi (Render, .env)."""
    for p in POSKYTOVATELE.values():
        if p["env"] and os.environ.get(p["env"]):
            cfg[p["klic"]] = os.environ[p["env"]]
    if os.environ.get("CLOUDFLARE_ACCOUNT_ID"):
        cfg["cloudflare_ucet"] = os.environ["CLOUDFLARE_ACCOUNT_ID"]


class LLMChyba(Exception):
    """Chyba volani modelu s hlaskou, kterou lze ukazat uzivateli (bez klicu a detailu)."""


def system_prompt():
    with open(PROMPT_PATH, encoding="utf-8") as f:
        return f.read()


def dostupne():
    try:
        import anthropic  # noqa: F401
        return True
    except ImportError:
        return False


def je_zdarma(cfg):
    """Bezplatny poskytovatel, nebo OpenRouter s modelem zdarma (":free", openrouter/free)."""
    prov = poskytovatel(cfg)
    model = (cfg.get(f"{prov}_model") or POSKYTOVATELE[prov]["model"] or "").lower()
    return bool(POSKYTOVATELE[prov].get("zdarma")) or model.endswith(":free") or model == "openrouter/free"


def poskytovatel(cfg):
    p = cfg.get("llm_poskytovatel") or "anthropic"
    return p if p in POSKYTOVATELE else "anthropic"


def nastaveni(cfg, prov=None):
    """Co se ma volat: dict(prov, nazev, typ, klic, model, url), nebo None, kdyz AI neni nastavena."""
    if cfg.get("llm_vypnuto"):
        return None
    prov = prov or poskytovatel(cfg)
    p = POSKYTOVATELE[prov]
    klic = (cfg.get(p["klic"]) or "") if p["klic"] else ""
    url = ((cfg.get(f"{prov}_url") if p.get("vlastni_url") else None) or p["url"] or "").rstrip("/")
    if p.get("ucet"):  # Cloudflare: adresa obsahuje Account ID
        ucet = cfg.get(f"{prov}_ucet") or ""
        if not re.fullmatch(UCET_RE, ucet):
            return None
        url = url.replace("{account_id}", ucet)
    model = cfg.get(f"{prov}_model") or p["model"]
    if p["klic"] and not klic and not p.get("klic_volitelny"):
        return None
    if p["typ"] == "openai" and not url:
        return None
    if not model:
        return None
    return {"prov": prov, "nazev": p["nazev"], "typ": p["typ"], "klic": klic, "model": model, "url": url}


def _text(resp):
    return "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")


def _parse_json(text):
    text = (text or "").strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1].rsplit("```", 1)[0]
    a, b = text.find("{"), text.rfind("}")
    if a < 0 or b < a:
        raise LLMChyba("model nevrátil JSON")
    d = json.loads(text[a:b + 1])
    if not isinstance(d, dict):
        raise LLMChyba("model nevrátil JSON objekt")
    return d


# ------------------------------------------------------------------ Anthropic
def _anthropic(n, system, user, schema, effort):
    import anthropic

    client = anthropic.Anthropic(api_key=n["klic"], timeout=120, max_retries=2)
    base = dict(model=n["model"], max_tokens=16000, system=system, messages=[{"role": "user", "content": user}])
    out_cfg = {"effort": effort, "format": {"type": "json_schema", "schema": schema}}
    try:
        # serverovy fallback na jiny model, kdyby bezpecnostni filtr pozadavek odmitl
        resp = client.beta.messages.create(**base, output_config=out_cfg,
                                           betas=["server-side-fallback-2026-07-01"], fallbacks="default")
    except anthropic.BadRequestError as e:
        log(A, f"structured output nepovolen ({e.message[:120]}), zkousim bez nej")
        resp = client.messages.create(**base, output_config={"effort": effort})
    if resp.stop_reason == "refusal":
        raise LLMChyba("model požadavek odmítl")
    if resp.stop_reason == "max_tokens":
        raise LLMChyba("odpověď byla useknutá")
    return _parse_json(_text(resp)), {"model": resp.model, "vstup_tokenu": resp.usage.input_tokens,
                                      "vystup_tokenu": resp.usage.output_tokens}


# ------------------------------------------------------------------ OpenAI-kompatibilni API
def _hlavicky(n):
    h = {"Content-Type": "application/json"}
    if n["klic"]:
        h["Authorization"] = f"Bearer {n['klic']}"
    return h


def _http_chyba(r):
    kod = r.status_code
    zprava = {401: "neplatný API klíč", 403: "klíč nemá oprávnění (nebo chybí kredit)", 404: "model nebo adresa API neexistuje",
              402: "došel kredit nebo je vyčerpaný limit klíče", 429: "překročen limit poskytovatele"}.get(kod, f"chyba API (HTTP {kod})")
    try:  # kratka hlaska od poskytovatele (bez hlavicek a klicu)
        detail = r.json().get("error")
        detail = detail.get("message") if isinstance(detail, dict) else detail
        if detail:
            zprava += f": {str(detail)[:140]}"
    except Exception:
        pass
    return LLMChyba(zprava)


def _openai(n, system, user, schema):
    url = n["url"] + "/chat/completions"
    zaklad = {"model": n["model"], "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]}
    formaty = [{"type": "json_schema", "json_schema": {"name": "odpoved", "strict": True, "schema": schema}},
               {"type": "json_object"}, None]
    r = None
    for f in formaty:  # ne kazdy model umi JSON schema -> zkusime jednodussi rezim
        telo = dict(zaklad, **({"response_format": f} if f else {}))
        for pokus in range(4):  # 429/402/5xx: kratke cekani s exponencialnim odstupem, jinak pravidla
            try:
                r = session().post(url, headers=_hlavicky(n), json=telo, timeout=180, allow_redirects=False)
            except Exception as e:
                raise LLMChyba(f"nelze se připojit k {n['nazev']} ({type(e).__name__})")
            if r.status_code not in (402, 429, 500, 502, 503, 529):
                break
            cekat = ai_limity.po_chybe(n, r.status_code, r.headers, r.text[:2000], pokus)
            if cekat is None:
                break
            log(A, f"{n['nazev']}: HTTP {r.status_code}, zkusim znovu za {cekat:.0f} s")
            time.sleep(cekat)
        if r.status_code in (400, 422) and f is not None:
            log(A, f"{n['nazev']}: response_format {f['type']} nepodporovan, zkousim jednodussi")
            continue
        break
    if r.status_code != 200:
        raise _http_chyba(r)
    ai_limity.po_odpovedi(n, r.headers)
    d = r.json()
    volba = (d.get("choices") or [{}])[0]
    msg = volba.get("message") or {}
    if msg.get("refusal"):
        raise LLMChyba("model požadavek odmítl")
    if volba.get("finish_reason") == "length":
        raise LLMChyba("odpověď byla useknutá")
    obsah = msg.get("content")
    if isinstance(obsah, list):
        obsah = "".join(c.get("text", "") for c in obsah if isinstance(c, dict))
    u = d.get("usage") or {}
    return _parse_json(obsah), {"model": d.get("model") or n["model"], "vstup_tokenu": u.get("prompt_tokens"),
                                "vystup_tokenu": u.get("completion_tokens")}


def zavolej(n, user_payload, schema, effort="medium", system=None):
    """n = nastaveni(cfg). Vrati (dict, info). Vyhodi vyjimku, kdyz se volani nepovede (volajici pak pouzije zaloznik)."""
    if n["typ"] == "openai":
        ai_limity.zivy_stav(n, session().get)  # OpenRouter: kolik dotazu zdarma dnes zbyva (60 s cache)
    proc_ne = ai_limity.pred_volanim(n)
    if proc_ne:
        raise LLMChyba(proc_ne)
    system = system or system_prompt()
    user = json.dumps(user_payload, ensure_ascii=False)
    if n["typ"] == "anthropic":
        if not dostupne():
            raise LLMChyba("chybí balíček anthropic (spusťte znovu TenderScope.bat)")
        d, info = _anthropic(n, system, user, schema, effort)
    else:
        d, info = _openai(n, system, user, schema)
    return d, {"poskytovatel": n["nazev"], **info}


def modely(n):
    """Seznam modelu, ktere poskytovatel nabizi (pro vyber v aplikaci). Nic nestoji."""
    if n["typ"] == "anthropic":
        import anthropic
        client = anthropic.Anthropic(api_key=n["klic"], timeout=30, max_retries=1)
        return sorted((m.id for m in client.models.list(limit=100)), reverse=True)
    try:
        r = session().get(n["url"] + "/models", headers=_hlavicky(n), timeout=30, allow_redirects=False)
    except Exception as e:
        raise LLMChyba(f"nelze se připojit k {n['nazev']} ({type(e).__name__})")
    if r.status_code != 200:
        raise _http_chyba(r)
    ids = [str(m.get("id", "")).removeprefix("models/") for m in r.json().get("data", []) if isinstance(m, dict)]
    return sorted({i for i in ids if i})[:500]


SCHEMA_TEST = {"type": "object", "properties": {"ok": {"type": "boolean"}, "pozdrav": {"type": "string"}},
               "required": ["ok", "pozdrav"], "additionalProperties": False}


def vyzkousej(n):
    """Kratky zkusebni dotaz (par tokenu)."""
    d, info = zavolej(n, {"ukol": "test spojeni"}, SCHEMA_TEST, effort="low",
                      system='Jsi test spojení. Odpověz pouze JSON objektem {"ok": true, "pozdrav": "<krátký český pozdrav>"}.')
    return {"ok": bool(d.get("ok")), "odpoved": str(d.get("pozdrav", ""))[:100], **info}


def chyba_text(e):
    """Srozumitelna hlaska pro uzivatele."""
    if isinstance(e, LLMChyba):
        return str(e)
    try:
        import anthropic
        if isinstance(e, anthropic.AuthenticationError):
            return "neplatný API klíč"
        if isinstance(e, anthropic.PermissionDeniedError):
            return "klíč nemá oprávnění k modelu"
        if isinstance(e, anthropic.NotFoundError):
            return "model neexistuje"
        if isinstance(e, anthropic.RateLimitError):
            return "překročen limit API, zkuste za chvíli"
        if isinstance(e, anthropic.APIConnectionError):
            return "nelze se připojit k API (internet/proxy)"
        if isinstance(e, anthropic.APIStatusError):
            return f"chyba API {e.status_code}"
    except ImportError:
        pass
    if isinstance(e, (json.JSONDecodeError, KeyError, TypeError, AttributeError)):
        return "model vrátil odpověď v nečekaném formátu"
    return type(e).__name__


# ------------------------------------------------------------------ JSON schemata
_STR = {"type": "string"}
_STRS = {"type": "array", "items": _STR}
VERTIKALY = ["stavebnictvi", "it_sw", "facility_sluzby", "dodavky_zbozi", "poradenstvi", "jine"]

SCHEMA_FAZE1 = {
    "type": "object",
    "properties": {
        "status": {"type": "string", "enum": ["needs_clarification"]},
        "detected_summary": _STR,
        "detected_vertical": {"type": "string", "enum": VERTIKALY},
        "questions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": _STR, "category": _STR, "question_text": _STR,
                    "quick_replies": _STRS, "allow_multiple": {"type": "boolean"},
                },
                "required": ["id", "category", "question_text", "quick_replies", "allow_multiple"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["status", "detected_summary", "detected_vertical", "questions"],
    "additionalProperties": False,
}

_NUM_OR_NULL = {"anyOf": [{"type": "number"}, {"type": "null"}]}
SCHEMA_FAZE2 = {
    "type": "object",
    "properties": {
        "status": {"type": "string", "enum": ["completed"]},
        "company_profile": {
            "type": "object",
            "properties": {
                "ico": _STR, "nazev": _STR,
                "vertical": {"type": "string", "enum": VERTIKALY},
                "core_capabilities_description": _STR,
                "cpv_codes": {"type": "object", "properties": {"main": _STRS, "secondary": _STRS},
                              "required": ["main", "secondary"], "additionalProperties": False},
                "keywords": _STRS, "negative_keywords": _STRS, "regions_nuts3": _STRS,
                "max_distance_km": _NUM_OR_NULL,
                "cooperation_model": {"anyOf": [_STR, {"type": "null"}]},
                "budget": {"type": "object", "properties": {"min_czk": _NUM_OR_NULL, "max_czk": _NUM_OR_NULL,
                                                            "vzmr_interest": {"type": "boolean"}},
                           "required": ["min_czk", "max_czk", "vzmr_interest"], "additionalProperties": False},
                "min_prep_days": {"type": "number"},
                "qualifications": _STRS, "consortium_ok": {"type": "boolean"}, "dealbreakers": _STRS,
                "whitelist_procurer_icos": _STRS, "blacklist_procurer_icos": _STRS,
            },
            "required": ["ico", "nazev", "vertical", "core_capabilities_description", "cpv_codes", "keywords",
                         "negative_keywords", "regions_nuts3", "max_distance_km", "cooperation_model", "budget",
                         "min_prep_days", "qualifications", "consortium_ok", "dealbreakers",
                         "whitelist_procurer_icos", "blacklist_procurer_icos"],
            "additionalProperties": False,
        },
    },
    "required": ["status", "company_profile"],
    "additionalProperties": False,
}
