"""Volani Claude API (Anthropic SDK) pro Onboarding agenta.

Klic zadava uzivatel v aplikaci (Data -> Claude API). Bez klice nebo pri chybe se pouzije
pravidlovy zaloznik v onboarding.py, takze aplikace funguje vzdy.
"""
import json
import os

from .util import log

A = "LLM"
DEFAULT_MODEL = "claude-opus-5-5"
PROMPT_PATH = os.path.join(os.path.dirname(__file__), "prompty", "onboarding_system.md")


def system_prompt():
    with open(PROMPT_PATH, encoding="utf-8") as f:
        return f.read()


def dostupne():
    try:
        import anthropic  # noqa: F401
        return True
    except ImportError:
        return False


def _text(resp):
    return "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")


def _parse_json(text):
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1].rsplit("```", 1)[0]
    a, b = text.find("{"), text.rfind("}")
    return json.loads(text[a:b + 1])


def zavolej(api_key, model, user_payload, schema, effort="medium"):
    """Vrati (dict, info). Vyhodi vyjimku, kdyz se volani nepovede (volajici pak pouzije zaloznik)."""
    import anthropic

    client = anthropic.Anthropic(api_key=api_key, timeout=120, max_retries=2)
    base = dict(
        model=model or DEFAULT_MODEL,
        max_tokens=16000,
        system=system_prompt(),
        messages=[{"role": "user", "content": json.dumps(user_payload, ensure_ascii=False)}],
    )
    out_cfg = {"effort": effort, "format": {"type": "json_schema", "schema": schema}}
    try:
        # serverovy fallback na jiny model, kdyby bezpecnostni filtr pozadavek odmitl
        resp = client.beta.messages.create(**base, output_config=out_cfg,
                                           betas=["server-side-fallback-2026-07-01"], fallbacks="default")
    except anthropic.BadRequestError as e:
        # napr. model bez structured outputs / fallbacku -> obycejne volani, JSON podle promptu
        log(A, f"structured output nepovolen ({e.message[:120]}), zkousim bez nej")
        resp = client.messages.create(**base, output_config={"effort": effort})
    if resp.stop_reason == "refusal":
        raise RuntimeError("model pozadavek odmitl (refusal)")
    if resp.stop_reason == "max_tokens":
        raise RuntimeError("odpoved byla useknuta (max_tokens)")
    data = _parse_json(_text(resp))
    info = {"model": resp.model, "vstup_tokenu": resp.usage.input_tokens, "vystup_tokenu": resp.usage.output_tokens}
    return data, info


def chyba_text(e):
    """Srozumitelna hlaska pro uzivatele."""
    try:
        import anthropic
        if isinstance(e, anthropic.AuthenticationError):
            return "neplatný Claude API klíč"
        if isinstance(e, anthropic.PermissionDeniedError):
            return "klíč nemá oprávnění k modelu"
        if isinstance(e, anthropic.RateLimitError):
            return "překročen limit API, zkuste za chvíli"
        if isinstance(e, anthropic.APIConnectionError):
            return "nelze se připojit k Claude API (internet/proxy)"
        if isinstance(e, anthropic.APIStatusError):
            return f"Claude API chyba {e.status_code}"
    except ImportError:
        pass
    return f"{type(e).__name__}: {str(e)[:160]}"


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
