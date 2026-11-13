import { useEffect, useMemo, useState } from "react";
import {
  api, type AgentInfo, type Faze1, type Kriterium, type Odpoved, type PolozkaZpravodaje, type Profil2, type Recon, type Srazka, type Zpravodaj,
} from "../api";
import { Card, go, Kpi, Loading } from "../components";
import { datum, kc, num } from "../format";

const KRAJE: [string, string][] = [
  ["CZ010", "Praha"], ["CZ020", "Středočeský"], ["CZ031", "Jihočeský"], ["CZ032", "Plzeňský"], ["CZ041", "Karlovarský"],
  ["CZ042", "Ústecký"], ["CZ051", "Liberecký"], ["CZ052", "Královéhradecký"], ["CZ053", "Pardubický"], ["CZ063", "Vysočina"],
  ["CZ064", "Jihomoravský"], ["CZ071", "Olomoucký"], ["CZ072", "Zlínský"], ["CZ080", "Moravskoslezský"],
];
const VERT: Record<string, string> = {
  stavebnictvi: "Stavebnictví", it_sw: "IT a software", facility_sluzby: "Facility a služby",
  dodavky_zbozi: "Dodávky zboží", poradenstvi: "Poradenství", jine: "Jiný obor",
};

function AgentBadge({ a }: { a: AgentInfo | null }) {
  if (!a) return null;
  return a.rezim === "llm" || a.rezim === "claude"
    ? <span className="badge good" title={`${a.vstup_tokenu ?? "?"} vstupních / ${a.vystup_tokenu ?? "?"} výstupních tokenů`}>Agent: {a.poskytovatel ?? "AI"} ({a.model})</span>
    : <span className="badge neutral" title={a.duvod}>Agent: pravidla{a.duvod ? ` – ${a.duvod}` : ""}</span>;
}

// ------------------------------------------------------------------ hlavni stranka
export default function Onboarding({ ico }: { ico: string | null }) {
  const [recon, setRecon] = useState<Recon | null>(null);
  const [f1, setF1] = useState<Faze1 | null>(null);
  const [agent1, setAgent1] = useState<AgentInfo | null>(null);
  const [odp, setOdp] = useState<Record<string, Odpoved>>({});
  const [profil, setProfil] = useState<Profil2 | null>(null);
  const [agent2, setAgent2] = useState<AgentInfo | null>(null);
  const [zprav, setZprav] = useState<Zpravodaj | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    setRecon(null); setF1(null); setProfil(null); setZprav(null); setErr(null); setAgent1(null); setAgent2(null);
    if (!ico) return;
    setBusy("Načítám uložený profil…");
    api.onbStav(ico)
      .then((s) => {
        setRecon(s.recon); setF1(s.faze1); setOdp(s.odpovedi ?? {}); setProfil(s.profil); setZprav(s.zpravodaj ?? null);
      })
      .catch((e) => setErr(String(e.message ?? e)))
      .finally(() => setBusy(null));
  }, [ico]);

  const start = async (i: string, web: string) => {
    setErr(null); setBusy("Recon agent prochází ARES, databázi zakázek, Registr smluv a web firmy, Onboarding agent píše otázky…");
    try {
      const r = await api.onbStart(i, web);
      setRecon(r.recon); setF1(r.faze1); setAgent1(r.agent); setOdp({}); setProfil(null); setZprav(null);
      if (`#/onboarding/${r.recon.ico}` !== window.location.hash) window.history.replaceState(null, "", `#/onboarding/${r.recon.ico}`);
    } catch (e) {
      setErr(String((e as Error).message ?? e));
    } finally {
      setBusy(null);
    }
  };

  const dokoncit = async () => {
    if (!recon) return;
    setErr(null); setBusy("Onboarding agent sestavuje profil a páruje ho se zakázkami za posledních 14 dní…");
    try {
      const r = await api.onbDokoncit(recon.ico, odp);
      setProfil(r.company_profile); setAgent2(r.agent); setZprav(r.zpravodaj);
      setTimeout(() => document.getElementById("profil")?.scrollIntoView({ behavior: "smooth" }), 50);
    } catch (e) {
      setErr(String((e as Error).message ?? e));
    } finally {
      setBusy(null);
    }
  };

  const ulozit = async (p: Profil2) => {
    setBusy("Přepočítávám zpravodaj…");
    try {
      const r = await api.onbUlozProfil(p.ico, p);
      setProfil(r.company_profile); setZprav(r.zpravodaj);
    } catch (e) {
      setErr(String((e as Error).message ?? e));
    } finally {
      setBusy(null);
    }
  };

  return (
    <div className="grid">
      <div>
        <h1>Onboarding firmy a Day-0 zpravodaj</h1>
        <p className="secondary" style={{ margin: "6px 0 0" }}>
          Zadejte IČO. Agenti potichu zjistí, co firma dělá, položí 4 cílené otázky, sestaví profil a hned ukážou zakázky, které by ji zajímaly.
        </p>
      </div>
      <StartForm initial={ico ?? ""} onStart={start} disabled={!!busy} />
      {err && <div className="callout">{err}</div>}
      {busy && <Card><Loading text={busy} /></Card>}
      {recon && f1 && <ReconCard recon={recon} f1={f1} agent={agent1} />}
      {recon && f1 && <Dotaznik f1={f1} odp={odp} setOdp={setOdp} onSubmit={dokoncit} disabled={!!busy} hotovo={!!profil} />}
      {profil && <ProfilCard profil={profil} agent={agent2} onSave={ulozit} disabled={!!busy} />}
      {zprav && profil && <ZpravodajCard z={zprav} profil={profil} />}
    </div>
  );
}

// ------------------------------------------------------------------ krok 0: IČO
function StartForm({ initial, onStart, disabled }: { initial: string; onStart: (ico: string, web: string) => void; disabled: boolean }) {
  const [ico, setIco] = useState(initial);
  const [web, setWeb] = useState("");
  const [seznam, setSeznam] = useState<{ ico: string; nazev: string | null; hotovo: boolean; vertical: string | null }[]>([]);
  useEffect(() => { setIco(initial); }, [initial]);
  useEffect(() => { api.onbSeznam().then(setSeznam).catch(() => undefined); }, [initial]);
  return (
    <Card title="1. Firma" sub="IČO stačí. Web je nepovinný – agent z něj vytáhne popis činnosti.">
      <form className="onb-start" onSubmit={(e) => { e.preventDefault(); if (ico.trim()) onStart(ico.trim(), web.trim()); }}>
        <label>
          <span className="small secondary">IČO</span>
          <input className="field" value={ico} onChange={(e) => setIco(e.target.value)} placeholder="např. 27082440" inputMode="numeric" />
        </label>
        <label>
          <span className="small secondary">Web firmy (nepovinné)</span>
          <input className="field" value={web} onChange={(e) => setWeb(e.target.value)} placeholder="např. www.firma.cz" />
        </label>
        <button className="btn primary" disabled={disabled || !ico.trim()}>Spustit rešerši</button>
      </form>
      {seznam.length > 0 && (
        <div className="row" style={{ marginTop: 14, gap: 8 }}>
          <span className="small muted">Uložené profily:</span>
          {seznam.slice(0, 12).map((s) => (
            <a key={s.ico} className="chip" href={`#/onboarding/${s.ico}`}>
              {s.nazev ?? s.ico} {s.hotovo ? "✓" : "…"}
            </a>
          ))}
        </div>
      )}
    </Card>
  );
}

// ------------------------------------------------------------------ krok 1: hypoteza
function ReconCard({ recon, f1, agent }: { recon: Recon; f1: Faze1; agent: AgentInfo | null }) {
  const h = recon.historie;
  return (
    <Card
      title={`2. Co agent zjistil: ${recon.nazev}`}
      sub={<>IČO {recon.ico} · {recon.sidlo?.adresa ?? "sídlo neuvedeno"}</>}
      right={<div className="row" style={{ gap: 6 }}><span className="badge neutral">{VERT[f1.detected_vertical] ?? f1.detected_vertical}</span><AgentBadge a={agent} /></div>}
    >
      <div className="hypo">{f1.detected_summary}</div>
      <div className="grid g4" style={{ marginTop: 14 }}>
        <Kpi label="Vyhrané zakázky" value={num(h.vyher)} note={`${num(h.ucasti)} známých účastí`} />
        <Kpi label="Objem výher" value={kc(h.objem_czk)} note={h.median_zakazky_czk ? `medián ${kc(h.median_zakazky_czk)}` : "bez dat"} />
        <Kpi label="Registr smluv" value={num(h.registr_smluv.pocet)} note={kc(h.registr_smluv.objem_czk)} />
        <Kpi label="Sídlo" value={recon.sidlo?.mesto ?? recon.sidlo?.kraj ?? "?"} note={recon.sidlo?.kraj ?? ""} />
      </div>
      <div className="row" style={{ marginTop: 12, gap: 6 }}>
        <span className="small muted">Zdroje:</span>
        {recon.zdroje.map((z) => (
          <a key={z.id} className={`chip ${z.ok ? "" : "off"}`} href={z.url ?? undefined} target="_blank" rel="noreferrer" title={z.ok ? "data nalezena" : "nic nenalezeno / nedostupné"}>
            {z.ok ? "✓" : "–"} {z.nazev} <span className="muted">[{z.rating}]</span>
          </a>
        ))}
      </div>
    </Card>
  );
}

// ------------------------------------------------------------------ krok 2: 4 otazky
function Dotaznik({ f1, odp, setOdp, onSubmit, disabled, hotovo }: {
  f1: Faze1; odp: Record<string, Odpoved>; setOdp: (o: Record<string, Odpoved>) => void; onSubmit: () => void; disabled: boolean; hotovo: boolean;
}) {
  const toggle = (qid: string, val: string, multi: boolean) => {
    const cur = odp[qid] ?? { vybrano: [], text: "" };
    const has = cur.vybrano.includes(val);
    const vybrano = multi ? (has ? cur.vybrano.filter((x) => x !== val) : [...cur.vybrano, val]) : (has ? [] : [val]);
    setOdp({ ...odp, [qid]: { ...cur, vybrano } });
  };
  const odpovezeno = f1.questions.filter((q) => (odp[q.id]?.vybrano.length ?? 0) > 0 || (odp[q.id]?.text ?? "").trim()).length;
  return (
    <Card title="3. Čtyři doplňující otázky" sub="Klikněte na předvolby (u některých jde vybrat víc) nebo dopište vlastní odpověď. Nevyplněné otázky agent doplní z historie firmy.">
      <div className="grid" style={{ gap: 18 }}>
        {f1.questions.map((q, i) => (
          <div key={q.id} className="otazka">
            <div className="small muted">{i + 1}. {q.category}{q.allow_multiple ? " · více možností" : ""}</div>
            <div className="otazka-text">{q.question_text}</div>
            <div className="row" style={{ gap: 8, marginTop: 8 }}>
              {q.quick_replies.map((r) => (
                <button key={r} type="button" className={`chip btnchip ${odp[q.id]?.vybrano.includes(r) ? "on" : ""}`} onClick={() => toggle(q.id, r, q.allow_multiple)}>
                  {r}
                </button>
              ))}
            </div>
            <input className="field" placeholder="Vlastní odpověď (nepovinné)" value={odp[q.id]?.text ?? ""}
              onChange={(e) => setOdp({ ...odp, [q.id]: { vybrano: odp[q.id]?.vybrano ?? [], text: e.target.value } })} />
          </div>
        ))}
      </div>
      <div className="row" style={{ marginTop: 16 }}>
        <button className="btn primary" disabled={disabled} onClick={onSubmit}>{hotovo ? "Znovu sestavit profil" : "Sestavit profil a zpravodaj"}</button>
        <span className="small muted">zodpovězeno {odpovezeno} ze 4</span>
      </div>
    </Card>
  );
}

// ------------------------------------------------------------------ krok 3: profil
const seznamText = (xs: string[]) => xs.join(", ");
const zText = (s: string) => s.split(/[,;\n]/).map((x) => x.trim()).filter(Boolean);

function ProfilCard({ profil, agent, onSave, disabled }: { profil: Profil2; agent: AgentInfo | null; onSave: (p: Profil2) => void; disabled: boolean }) {
  const [p, setP] = useState(profil);
  const [json, setJson] = useState(false);
  useEffect(() => setP(profil), [profil]);
  const set = (patch: Partial<Profil2>) => setP({ ...p, ...patch });
  const toggleKraj = (k: string) => {
    let r = p.regions_nuts3.filter((x) => x !== "CZ0");
    r = r.includes(k) ? r.filter((x) => x !== k) : [...r, k];
    set({ regions_nuts3: r.length ? r : ["CZ0"] });
  };
  const stahnout = () => {
    const { sidlo: _s, ...bez } = p;
    const blob = new Blob([JSON.stringify({ status: "completed", company_profile: bez }, null, 2)], { type: "application/json" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `company_profile_${p.ico}.json`;
    a.click();
  };
  const cela = p.regions_nuts3.includes("CZ0");
  return (
    <div id="profil">
      <Card title="4. Profil firmy (company_profile)" sub="Podle tohoto profilu se filtrují a hodnotí zakázky. Cokoli upravte a klikněte Uložit – zpravodaj se přepočítá."
        right={<div className="row" style={{ gap: 6 }}><span className="badge neutral">{VERT[p.vertical] ?? p.vertical}</span><AgentBadge a={agent} /></div>}>
        <label className="lbl">Popis kompetencí (z něj se počítá textová podobnost se zakázkami)</label>
        <textarea className="field" rows={3} value={p.core_capabilities_description} onChange={(e) => set({ core_capabilities_description: e.target.value })} />
        <div className="grid g2" style={{ marginTop: 10 }}>
          <div>
            <label className="lbl">Hlavní CPV kódy</label>
            <input className="field mono" value={seznamText(p.cpv_codes.main)} onChange={(e) => set({ cpv_codes: { ...p.cpv_codes, main: zText(e.target.value) } })} />
            {p.cpv_zdroj && <div className="small muted" style={{ marginTop: 2 }}>{p.cpv_zdroj}</div>}
            <label className="lbl">Vedlejší CPV kódy</label>
            <input className="field mono" value={seznamText(p.cpv_codes.secondary)} onChange={(e) => set({ cpv_codes: { ...p.cpv_codes, secondary: zText(e.target.value) } })} />
            <label className="lbl">Klíčová slova</label>
            <input className="field" value={seznamText(p.keywords)} onChange={(e) => set({ keywords: zText(e.target.value) })} />
            <label className="lbl">Negativní klíčová slova (zakázka s nimi = nevhodná)</label>
            <input className="field" value={seznamText(p.negative_keywords)} onChange={(e) => set({ negative_keywords: zText(e.target.value) })} />
            <label className="lbl">Kvalifikace a oprávnění</label>
            <input className="field" value={seznamText(p.qualifications)} onChange={(e) => set({ qualifications: zText(e.target.value) })} />
            <div className="grid g2" style={{ gap: 10 }}>
              <label><span className="lbl">Roční obrat firmy (Kč)</span>
                <input className="field" type="number" placeholder="např. 50000000" value={p.obrat_czk ?? ""}
                  onChange={(e) => set({ obrat_czk: e.target.value ? Number(e.target.value) : null })} /></label>
              <label className="row" style={{ gap: 8, alignSelf: "end", paddingBottom: 10 }}>
                <input type="checkbox" checked={!!p.consortium_ok} onChange={(e) => set({ consortium_ok: e.target.checked })} />
                <span className="small">Půjdeme i do konsorcia / s poddodavatelem</span></label>
            </div>
            <p className="small secondary" style={{ margin: "4px 0 0" }}>Obrat slouží k odhadu, zda firma splní kvalifikaci (zadavatel smí chtít nejvýš 2× hodnotu zakázky). Bez něj se počítá s veřejnými tržbami z RVZ a Registru smluv.</p>
          </div>
          <div>
            <div className="grid g3" style={{ gap: 10 }}>
              <label><span className="lbl">Rozpočet od (Kč)</span>
                <input className="field" type="number" value={p.budget.min_czk ?? ""} onChange={(e) => set({ budget: { ...p.budget, min_czk: e.target.value ? Number(e.target.value) : null } })} /></label>
              <label><span className="lbl">Rozpočet do (Kč)</span>
                <input className="field" type="number" value={p.budget.max_czk ?? ""} onChange={(e) => set({ budget: { ...p.budget, max_czk: e.target.value ? Number(e.target.value) : null } })} /></label>
              <label><span className="lbl">Příprava min. (dní)</span>
                <input className="field" type="number" value={p.min_prep_days} onChange={(e) => set({ min_prep_days: Number(e.target.value) || 1 })} /></label>
            </div>
            <label className="lbl">Max. vzdálenost od sídla (km){p.sidlo?.mesto ? ` – sídlo ${p.sidlo.mesto}` : p.sidlo?.kraj ? ` – sídlo ${p.sidlo.kraj}` : ""}</label>
            <input className="field" type="number" placeholder="bez limitu (vzdálené plnění)" value={p.max_distance_km ?? ""}
              onChange={(e) => set({ max_distance_km: e.target.value ? Number(e.target.value) : null })} />
            <label className="lbl">Regiony CZ-NUTS 3</label>
            <div className="row" style={{ gap: 6, marginTop: 4 }}>
              <button type="button" className={`chip btnchip ${cela ? "on" : ""}`} onClick={() => set({ regions_nuts3: ["CZ0"] })}>Celá ČR (CZ0)</button>
              {KRAJE.map(([k, n]) => (
                <button key={k} type="button" className={`chip btnchip ${!cela && p.regions_nuts3.includes(k) ? "on" : ""}`} onClick={() => toggleKraj(k)} title={k}>{n}</button>
              ))}
            </div>
            <div className="row small" style={{ marginTop: 10, gap: 14 }}>
              <label><input type="checkbox" checked={p.budget.vzmr_interest} onChange={(e) => set({ budget: { ...p.budget, vzmr_interest: e.target.checked } })} /> zájem o VZMR</label>
              <label><input type="checkbox" checked={p.consortium_ok} onChange={(e) => set({ consortium_ok: e.target.checked })} /> konsorcia / subdodávky</label>
              {p.cooperation_model && <span className="secondary">model: {p.cooperation_model}</span>}
            </div>
            <label className="lbl">Dealbreakery</label>
            <ul className="small secondary" style={{ margin: "4px 0 0", paddingLeft: 18 }}>{p.dealbreakers.map((d) => <li key={d}>{d}</li>)}</ul>
            <div className="small muted" style={{ marginTop: 6 }}>Whitelist zadavatelů (dosavadní klienti): {p.whitelist_procurer_icos.length}</div>
          </div>
        </div>
        <div className="row" style={{ marginTop: 14 }}>
          <button className="btn primary" disabled={disabled} onClick={() => onSave(p)}>Uložit a přepočítat zpravodaj</button>
          <button className="btn" onClick={() => setJson(!json)}>{json ? "Skrýt JSON" : "Zobrazit JSON"}</button>
          <button className="btn" onClick={stahnout}>Stáhnout JSON</button>
          <a className="btn" href={`#/firma/${p.ico}`}>Konkurenceschopnost firmy →</a>
        </div>
        {json && <div className="log" style={{ marginTop: 12 }}>{JSON.stringify({ status: "completed", company_profile: p }, null, 2)}</div>}
      </Card>
    </div>
  );
}

// ------------------------------------------------------------------ krok 4: zpravodaj + dotaznik vhodnosti
type Rucne = Record<string, Record<string, "ano" | "ne" | "nevim">>;
const RUCNI = [
  { klic: "kvalifikace", otazka: "Splníme kvalifikaci a máme reference?", vaha: 5 },
  { klic: "kapacita", otazka: "Máme v termínu plnění volnou kapacitu?", vaha: 10 },
];

// stejny model jako ts/onboarding.py skore_z_kriterii: vazeny prumer (zaklad) x srazky za vylucujici duvody
function skoreZKriterii(kr: Kriterium[], srazky: Srazka[]) {
  const pl = kr.filter((c) => c.skore !== null);
  const sv = pl.reduce((a, c) => a + c.vaha, 0);
  for (const c of kr) c.body = c.skore !== null && sv ? Math.round(((c.skore as number) * c.vaha / sv) * 10) / 10 : null;
  const zaklad = sv ? pl.reduce((a, c) => a + (c.skore as number) * c.vaha, 0) / sv : 0;
  const faktor = srazky.reduce((f, s) => f * (1 - s.zavaznost), 1);
  const skore = Math.round(zaklad * faktor);
  const ko = srazky.filter((s) => s.zavaznost >= 0.5).map((s) => s.duvod);
  const verdikt = ko.length ? "nevhodné" : skore >= 70 ? "doporučeno" : skore >= 50 ? "zvážit" : "spíš ne";
  return { skore, zaklad: Math.round(zaklad), srazky, verdikt, ko, kriteria: kr };
}

function prepocet(p: PolozkaZpravodaje, r: Record<string, "ano" | "ne" | "nevim"> | undefined) {
  const kr: Kriterium[] = p.kriteria.filter((c) => c.klic !== "kvalifikace").map((c) => ({ ...c }));
  const srazky: Srazka[] = (p.srazky ?? []).filter((s) => !(s.klic === "kvalifikace" && r?.kvalifikace));
  for (const q of RUCNI) {
    const v = r?.[q.klic];
    const auto = p.kriteria.find((c) => c.klic === q.klic);
    if (v === "ano") kr.push({ klic: q.klic, otazka: q.otazka, odpoved: "ano (vaše odpověď)", skore: 100, vaha: q.vaha, rucne: true });
    else if (v === "ne") {
      kr.push({ klic: q.klic, otazka: q.otazka, odpoved: "ne (vaše odpověď)", skore: 0, vaha: q.vaha, rucne: true });
      srazky.push({ duvod: q.otazka.replace("?", "") + ": ne", zavaznost: 0.6, klic: q.klic });
    }
    else if (auto) kr.push({ ...auto, rucne: true });
    else kr.push({ klic: q.klic, otazka: q.otazka, odpoved: "nevyplněno", skore: null, vaha: q.vaha, rucne: true });
  }
  return skoreZKriterii(kr, srazky);
}

const VCLASS: Record<string, string> = { "doporučeno": "good", "zvážit": "warn", "spíš ne": "neutral", "nevhodné": "bad" };

function ZpravodajCard({ z, profil }: { z: Zpravodaj; profil: Profil2 }) {
  const [rucne, setRucne] = useState<Rucne>({});
  const [filtr, setFiltr] = useState<"vse" | "otevrene" | "doporucene">("vse");
  const [open, setOpen] = useState<string | null>(null);
  const items = useMemo(() => z.polozky.map((p) => ({ p, v: prepocet(p, rucne[p.id]) })), [z, rucne]);
  const shown = items
    .filter(({ p, v }) => filtr === "vse" || (filtr === "otevrene" ? p.otevrena : v.verdikt === "doporučeno"))
    .sort((a, b) => b.v.skore - a.v.skore);
  const pocty = { dop: items.filter((x) => x.v.verdikt === "doporučeno").length, otev: items.filter((x) => x.p.otevrena).length };
  return (
    <Card title={`5. Day-0 zpravodaj pro ${profil.nazev}`}
      sub={<>Zakázky vyhlášené {datum(z.od)} – {datum(z.do)} a všechny ještě otevřené. Prošlo {num(z.kandidatu)} zakázek, předmětem sedí {num(z.polozky.length)}, doporučeno {num(pocty.dop)}.</>}>
      {z.poznamka && <div className="callout info" style={{ marginBottom: 12 }}>{z.poznamka}</div>}
      <div className="row" style={{ gap: 6, marginBottom: 12 }}>
        {([["vse", `Vše (${items.length})`], ["doporucene", `Doporučené (${pocty.dop})`], ["otevrene", `Otevřené (${pocty.otev})`]] as const).map(([k, l]) => (
          <button key={k} className={`chip btnchip ${filtr === k ? "on" : ""}`} onClick={() => setFiltr(k)}>{l}</button>
        ))}
      </div>
      {shown.length === 0 && <div className="empty">Nic tu není. Zkuste upravit CPV kódy nebo regiony v profilu.</div>}
      <div className="zprav">
        {shown.map(({ p, v }) => (
          <div key={p.id} className="zp">
            <button className="zp-head" onClick={() => setOpen(open === p.id ? null : p.id)} aria-expanded={open === p.id}>
              <span className={`skore-kruh ${VCLASS[v.verdikt]}`}>{v.skore}</span>
              <span className="zp-main">
                <span className="zp-title">{p.nazev}</span>
                <span className="small secondary">
                  {p.zadavatel ?? "?"} · {p.kraj ?? "?"}{p.kriteria.find((c) => c.km !== undefined) ? ` (${p.kriteria.find((c) => c.km !== undefined)?.km} km)` : ""} · {kc(p.hodnota)} · lhůta {datum(p.lhuta)}
                  {!p.otevrena && " · uplynula"}
                </span>
              </span>
              <span className={`badge ${VCLASS[v.verdikt]}`}>{v.verdikt}</span>
            </button>
            {open === p.id && (
              <div className="zp-body">
                <Identifikatory p={p} />
                {v.ko.length > 0 && <div className="callout" style={{ marginBottom: 10 }}>Vylučující důvody: {v.ko.join(" · ")}</div>}
                <div className="table-wrap">
                  <table>
                    <thead><tr><th>Otázka</th><th>Odpověď</th><th style={{ textAlign: "right" }}>Váha</th><th style={{ textAlign: "right" }}>Skóre</th><th style={{ textAlign: "right" }} title="Kolik bodů z celkových 100 přinesla otázka (skóre × váha / součet vah)">Body</th></tr></thead>
                    <tbody>
                      {v.kriteria.map((c) => (
                        <tr key={c.klic}>
                          <td>{c.otazka}</td>
                          <td>
                            {c.rucne ? (
                              <div className="row" style={{ gap: 6 }}>
                                {(["ano", "ne", "nevim"] as const).map((o) => (
                                  <button key={o} className={`chip btnchip ${rucne[p.id]?.[c.klic] === o ? "on" : ""}`}
                                    onClick={() => setRucne({ ...rucne, [p.id]: { ...(rucne[p.id] ?? {}), [c.klic]: o } })}>
                                    {o === "nevim" ? "nevím" : o}
                                  </button>
                                ))}
                                <span className="small muted">{c.odpoved}</span>
                              </div>
                            ) : c.odpoved}
                          </td>
                          <td className="num">{c.vaha}</td>
                          <td className="num">{c.skore ?? "–"}</td>
                          <td className="num">{c.body ?? "–"}</td>
                        </tr>
                      ))}
                    </tbody>
                    <tfoot>
                      <tr><td colSpan={4}><b>Základ</b> <span className="muted small">(vážený průměr otázek s odpovědí)</span></td><td className="num"><b>{v.zaklad}</b></td></tr>
                      {v.srazky.map((s, i) => (
                        <tr key={i}><td colSpan={4}>Srážka: {s.duvod}</td><td className="num">× {(1 - s.zavaznost).toFixed(2)}</td></tr>
                      ))}
                      <tr><td colSpan={4}><b>Celkové skóre</b></td><td className="num"><b>{v.skore}</b></td></tr>
                    </tfoot>
                  </table>
                </div>
                <div className="row small" style={{ marginTop: 8 }}>
                  <span className="muted">{p.segment}</span>
                  {(p.odkazy ?? (p.url ? [{ nazev: "Detail zakázky", url: p.url }] : [])).map((o) => (
                    <a key={o.url} href={o.url} target="_blank" rel="noreferrer">{o.nazev} ↗</a>
                  ))}
                  {p.zadavatel_ico && <a href={`#/trh`} onClick={(e) => { e.preventDefault(); go(`/trh/${encodeURIComponent(p.segment)}`); }}>Trh v segmentu →</a>}
                </div>
              </div>
            )}
          </div>
        ))}
      </div>
    </Card>
  );
}

function Identifikatory({ p }: { p: PolozkaZpravodaje }) {
  const radky: [string, string | null | undefined, string][] = [
    ["Identifikátor NIPEZ", p.nipez_id, "číslo zakázky v Registru veřejných zakázek – zadejte ho do vyhledávání na NEN nebo Hlídači státu"],
    ["Systémové číslo NEN", p.nen_cislo, "číslo zakázky v Národním elektronickém nástroji"],
    ["Ev. číslo ve Věstníku", p.vvz_cislo, "evidenční číslo zakázky ve Věstníku veřejných zakázek"],
  ];
  const jsou = radky.filter((r) => r[1]);
  if (!jsou.length) return null;
  return (
    <div className="row small" style={{ gap: 14, marginBottom: 10, flexWrap: "wrap" }}>
      {jsou.map(([n, v, t]) => (
        <span key={n} title={t}><span className="muted">{n}:</span> <b className="mono">{v}</b>{" "}
          <button className="chip btnchip" onClick={() => navigator.clipboard?.writeText(v as string)} title="Zkopírovat">kopírovat</button>
        </span>
      ))}
    </div>
  );
}
