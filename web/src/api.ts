// Typy a volani backendu (server.py)

export interface GrafUzel { id: string; typ: "firma" | "obor" | "zadavatel" | "konkurent" | "zakazka" | "zdroj"; nazev: string; odkaz: string | null; vaha: number; info: string | null }
export interface Graf { ico: string; nazev: string; uzly: GrafUzel[]; hrany: { od: string; do: string; typ: string; popis: string | null }[] }

export interface Obdobi {
  rvz_od: string | null;
  rvz_do: string | null;
  rvz_mesicu: number;
  rs_od: string | null;
  rs_do: string | null;
  rs_mesicu: number;
}

export interface Stav {
  demo: boolean;
  zakazek: number;
  vitezu: number;
  dodavatelu: number;
  smluv: number;
  firem_ares: number;
  od: string | null;
  do: string | null;
  posledni_aktualizace: string | null;
  aktualizace_bezi: boolean;
  verejne?: boolean;
  obdobi?: Obdobi;
}

export interface Hit {
  ico: string;
  nazev: string | null;
  vyhry: number;
  ucasti: number;
  objem: number;
  smluv_rs: number;
  jen_ares?: boolean;
}

export interface Slozka {
  klic: string;
  nazev: string;
  vaha: number;
  skore: number | null;
  vysvetleni: string;
  malo_dat?: boolean;
}

export interface Profil {
  ico: string;
  nazev: string;
  ares: {
    nazev?: string;
    sidlo?: string;
    kraj?: string;
    nace?: string;
    datum_vzniku?: string;
    datum_zaniku?: string | null;
  } | null;
  kpi: {
    vyhry: number;
    ucasti: number;
    ucasti_zname: number;
    win_rate: number | null;
    objem: number;
    median_cena: number | null;
    median_pomer: number | null;
    trh_median_pomer: number | null;
    klientu: number;
    prumer_nabidek: number | null;
    jedna_nabidka: number;
    s_poctem_nabidek: number;
    smluv_rs: number;
    objem_rs: number;
    smluv_rs_souhrn?: number;
    objem_rs_souhrn?: number;
    overeno_rs: number;
  };
  registr?: {
    pocet: number;
    objem: number;
    zadavatelu: number;
    mesice: { mesic: string; pocet: number; objem: number }[];
    odberatele: { ico: string; nazev: string; pocet: number; objem: number }[];
  } | null;
  obdobi?: Obdobi;
  hlidac?: { url: string; pocet: number | null };
  skore: { celkem: number | null; hodnoceni: string | null; slozky: Slozka[]; malo_dat?: boolean };
  mesice: { mesic: string; vyhry: number; objem: number; ucasti: number }[];
  segmenty: {
    segment: string;
    vyhry: number;
    objem: number;
    podil: number | null;
    poradi: number | null;
    dodavatelu: number;
    median_pomer: number | null;
    trh_median_pomer: number | null;
    trh_objem: number;
  }[];
  klienti: { ico: string; nazev: string; vyhry: number; objem: number }[];
  ceny: { nazev: string; odhad: number; cena: number; pomer: number; segment: string }[];
  souboje: { ico: string; nazev: string; stretu: number; my_vyhra: number; oni_vyhra: number }[];
  rivalove: { ico: string; nazev: string; objem: number; vyhry: number }[];
  regiony: { kraj: string; pocet: number }[];
  prilezitosti: { id: string; nazev: string; zadavatel: string; hodnota: number | null; lhuta: string; url: string | null; duvody: string[]; klient: boolean }[];
  zakazky: {
    id: string;
    nazev: string;
    zadavatel: string;
    datum: string | null;
    odhad: number | null;
    cena: number | null;
    vysledek: string;
    nabidek: number | null;
    segment: string;
    url: string | null;
    overeno_rs: boolean;
  }[];
  priznaky: { typ: string; popis: string }[];
  zpravy: { titulek: string; url: string; datum: string | null; zdroj: string | null }[];
}

export interface Trh {
  segment: string | null;
  zakazek: number;
  hodnota: number;
  mesice: { mesic: string; pocet: number }[];
  kraje: { kraj: string; pocet: number }[];
  segmenty: { segment: string; pocet: number; odhad?: number }[];
  odhadnuto?: number;
  top: { ico: string; nazev: string; vyhry: number; objem: number; podil: number }[];
}

export interface Beh {
  bezi: boolean;
  rezim: string | null;
  chyba: string | null;
  zacatek: string | null;
  konec: string | null;
  log: string[];
}

export interface Nastaveni {
  verejne?: boolean;
  admin?: boolean;
  obsidian_vault: string;
  exa_api_key_nastaven: boolean;
  exa_api_key_nahled: string;
  ai: { poskytovatel: string; pripraveno: boolean; model: string | null; anthropic_sdk: boolean; poskytovatele: AiPoskytovatel[] };
  limity?: { ai_dnes: number; ai_max: number | null; ai_limit_env?: boolean; ai_limit_nastaveny?: number | null; ai_vychozi?: string; exa_dnes: number; exa_max: number };
}
export interface AiPoskytovatel {
  id: string; nazev: string; web: string; potrebuje_klic: boolean; ma_klic_pole: boolean; vlastni_url: boolean; env: string | null;
  klic_nastaven: boolean; klic_nahled: string; model: string; model_vychozi: string; url: string;
  zdarma: boolean; limit: string; pozn: string; soukromi_ok: boolean; potrebuje_ucet: boolean; ucet: string;
}
export interface AiLimity {
  ok: boolean; chyba?: string; poskytovatel?: string; model?: string;
  limity?: { rpm?: number; rph?: number; rpd?: number; tpm?: number; tpd?: number; mesicne?: number; soubezne?: number; pozn?: string; zdroj?: string };
  za_minutu?: number; dnes?: number; za_mesic?: number;
  pauza?: { duvod: string; zbyva: string } | null;
  hlavicky?: { zbyva_dotazu?: number | null; limit_dotazu?: number | null; zbyva_tokenu?: number | null } | null;
  zivy?: { denni_limit?: number | null; denni_pouzito?: number | null; denni_zbyva?: number | null; kredit_zbyva?: number | null } | null;
  aplikace?: { dnes: number; max: number | null };
}
export interface AiForm { llm_poskytovatel?: string; llm_klic?: string; llm_model?: string; llm_url?: string; llm_ucet?: string; ai_denni_limit?: number | string | null }

// ---------------- onboarding
export interface Otazka { id: string; category: string; question_text: string; quick_replies: string[]; allow_multiple: boolean }
export interface Faze1 { status: "needs_clarification"; detected_summary: string; detected_vertical: string; questions: Otazka[] }
export interface Zdroj { id: string; nazev: string; url: string | null; rating: string; ok: boolean }
export interface Sidlo { adresa: string | null; mesto: string | null; nuts3: string | null; kraj: string | null; lat: number | null; lon: number | null; presnost: string | null }
export interface Recon {
  ico: string;
  nazev: string;
  ares: { nazev?: string; sidlo?: string; kraj?: string; nace?: string } | null;
  sidlo: Sidlo;
  historie: {
    vyher: number; ucasti: number; objem_czk: number; median_zakazky_czk: number | null;
    top_cpv: { cpv: string; pocet: number; segment: string }[];
    top_zadavatele: { ico: string; nazev: string | null; pocet: number; objem: number }[];
    kraje: { nuts3: string; kraj: string; pocet: number }[];
    registr_smluv: { pocet: number; objem_czk: number };
  };
  web: { url: string; titulek?: string | null; popis?: string | null; chyba?: string } | null;
  zdroje: Zdroj[];
}
export interface AgentInfo { rezim: "llm" | "claude" | "pravidla"; duvod?: string; poskytovatel?: string; model?: string; vstup_tokenu?: number; vystup_tokenu?: number }
export interface Profil2 {
  ico: string; nazev: string; vertical: string; core_capabilities_description: string;
  cpv_codes: { main: string[]; secondary: string[] };
  keywords: string[]; negative_keywords: string[]; regions_nuts3: string[];
  max_distance_km: number | null; cooperation_model: string | null;
  budget: { min_czk: number | null; max_czk: number | null; vzmr_interest: boolean };
  min_prep_days: number; qualifications: string[]; consortium_ok: boolean; dealbreakers: string[]; obrat_czk?: number | null; cpv_zdroj?: string;
  whitelist_procurer_icos: string[]; blacklist_procurer_icos: string[];
  sidlo?: Sidlo;
}
export interface Kriterium { klic: string; otazka: string; odpoved: string; skore: number | null; vaha: number; body?: number | null; km?: number; rucne?: boolean; uplynula?: boolean }
export interface Srazka { duvod: string; zavaznost: number; klic: string }
export interface Odkaz { nazev: string; url: string }
export interface PolozkaZpravodaje {
  id: string; nazev: string; zadavatel: string | null; zadavatel_ico: string | null; kraj: string | null; hodnota: number | null;
  datum: string | null; lhuta: string; otevrena: boolean; url: string | null; segment: string;
  skore: number; verdikt: string; ko: string[]; kriteria: Kriterium[]; zaklad?: number; srazky?: Srazka[];
  odkazy?: Odkaz[]; nipez_id?: string | null; nen_cislo?: string | null; vvz_cislo?: string | null;
}
export interface Zpravodaj { od: string | null; do: string | null; poznamka: string | null; kandidatu: number; doporuceno?: number; polozky: PolozkaZpravodaje[] }
export interface OnbStav { ico: string; recon: Recon | null; faze1: Faze1 | null; odpovedi: Record<string, Odpoved> | null; profil: Profil2 | null; zpravodaj?: Zpravodaj; upraveno: string }
export interface Odpoved { vybrano: string[]; text: string }

export interface ExportVysledek {
  ok: boolean;
  nazev: string;
  poznamek: number;
  zdroju: number;
  exa: number;
  zip: string;
  zapsano: string | null;
  chyba_zapisu?: string;
}

export const ADMIN_KEY = "ts_admin_heslo";
export function adminHeslo(): string {
  try { return localStorage.getItem(ADMIN_KEY) || ""; } catch { return ""; }
}
export function nastavAdminHeslo(h: string) {
  try { if (h) localStorage.setItem(ADMIN_KEY, h); else localStorage.removeItem(ADMIN_KEY); } catch { /* bez uloziste */ }
}
/** Nahodne ID tohoto prohlizece. Na online verzi podle nej server oddeluje onboardingy
 *  jednotlivych navstevniku (kdo ID nezna, cizi profil neuvidi). Neni to heslo ani osobni udaj. */
let _uid = "";
function uzivatelId(): string {
  if (_uid) return _uid;
  try { _uid = localStorage.getItem("ts_uzivatel") || ""; } catch { /* bez uloziste */ }
  if (!/^[A-Za-z0-9-]{16,64}$/.test(_uid)) {
    const b = new Uint8Array(16);
    crypto.getRandomValues(b);
    _uid = Array.from(b, (x) => x.toString(16).padStart(2, "0")).join("");
    try { localStorage.setItem("ts_uzivatel", _uid); } catch { /* bez uloziste: ID plati do zavreni stranky */ }
  }
  return _uid;
}

/** Hlavicky pro server; na verejne (online) verzi nese admin heslo a ID prohlizece. */
function hdr(json = true): Record<string, string> {
  const h: Record<string, string> = json ? { "Content-Type": "application/json" } : {};
  h["X-Uzivatel"] = uzivatelId();
  const a = adminHeslo();
  if (a) h["X-Admin-Heslo"] = encodeURIComponent(a);
  return h;
}

async function post<T>(url: string, body: unknown): Promise<T> {
  const r = await fetch(url, { method: "POST", headers: hdr(), body: JSON.stringify(body) });
  const data = await r.json();
  if (!r.ok) throw new Error(data?.chyba || `HTTP ${r.status}`);
  return data as T;
}

async function get<T>(url: string): Promise<T> {
  const r = await fetch(url, { headers: hdr(false) });
  const data = await r.json();
  if (!r.ok) throw new Error(data?.chyba || `HTTP ${r.status}`);
  return data as T;
}

export const api = {
  stav: () => get<Stav>("/api/stav"),
  hledat: (q: string) => get<Hit[]>(`/api/hledat?q=${encodeURIComponent(q)}`),
  firma: (ico: string) => get<Profil>(`/api/firma/${encodeURIComponent(ico)}`),
  graf: (ico: string) => get<Graf>(`/api/graf/${encodeURIComponent(ico)}`),
  trh: (segment?: string | null) => get<Trh>(`/api/trh${segment ? `?segment=${encodeURIComponent(segment)}` : ""}`),
  beh: () => get<Beh>("/api/beh"),
  nastaveni: () => get<Nastaveni>("/api/nastaveni"),
  onbSeznam: () => get<{ ico: string; nazev: string | null; hotovo: boolean; vertical: string | null; upraveno: string }[]>("/api/onboarding"),
  onbStav: (ico: string) => get<OnbStav>(`/api/onboarding/${encodeURIComponent(ico)}`),
  onbStart: (ico: string, web: string) => post<{ recon: Recon; faze1: Faze1; agent: AgentInfo }>("/api/onboarding/start", { ico, web }),
  onbDokoncit: (ico: string, odpovedi: Record<string, Odpoved>) =>
    post<{ company_profile: Profil2; agent: AgentInfo; zpravodaj: Zpravodaj }>("/api/onboarding/dokoncit", { ico, odpovedi }),
  onbUlozProfil: (ico: string, profil: Profil2) =>
    post<{ company_profile: Profil2; zpravodaj: Zpravodaj }>(`/api/onboarding/${encodeURIComponent(ico)}/profil`, { profil }),
  aiModely: (body: AiForm) => post<{ ok: boolean; modely?: string[]; chyba?: string }>("/api/ai/modely", body),
  aiLimity: () => post<AiLimity>("/api/ai/limity", {}),
  aiTest: (body: AiForm) => post<{ ok: boolean; odpoved?: string; chyba?: string; poskytovatel?: string; model?: string }>("/api/ai/test", body),
  ulozNastaveni: async (body: AiForm & { obsidian_vault?: string; exa_api_key?: string }) => {
    const r = await fetch("/api/nastaveni", { method: "POST", headers: hdr(), body: JSON.stringify(body) });
    const d = await r.json();
    if (!r.ok) throw new Error(d?.chyba || `HTTP ${r.status}`);
    return d as Nastaveni;
  },
  export: async (ico: string) => {
    const r = await fetch(`/api/export/${encodeURIComponent(ico)}`, { method: "POST", headers: hdr(), body: JSON.stringify({ zapsat: true }) });
    const d = await r.json();
    if (!r.ok) throw new Error(d?.chyba || `HTTP ${r.status}`);
    return d as ExportVysledek;
  },
  diagnostika: (ico?: string) => get<Record<string, unknown>>(`/api/diagnostika${ico ? `?ico=${encodeURIComponent(ico)}` : ""}`),
  aktualizovat: async (rezim: "rychle" | "plny") => {
    const r = await fetch("/api/aktualizovat", {
      method: "POST",
      headers: hdr(),
      body: JSON.stringify({ rezim }),
    });
    const d = await r.json();
    if (!r.ok) throw new Error(d?.chyba || d?.zprava || `HTTP ${r.status}`);
    return d;
  },
};
