import { useEffect, useMemo, useState } from "react";
import {
  api, type AgentInfo, type CiAnalyza, type Dukaz, type Faze1, type Kriterium, type NalezFirmy, type Odpoved, type PolozkaZpravodaje, type Profil2,
  type Recon, type Srazka, type Zpravodaj,
} from "../api";
import { Card, go, Kpi } from "../components";
import { datum, kc, num } from "../format";
import { CPV_VYSVETLENI, oborKodu, zdrojLidsky } from "../cpv";

const KRAJE: [string, string][] = [
  ["CZ010", "Praha"], ["CZ020", "Středočeský"], ["CZ031", "Jihočeský"], ["CZ032", "Plzeňský"], ["CZ041", "Karlovarský"],
  ["CZ042", "Ústecký"], ["CZ051", "Liberecký"], ["CZ052", "Královéhradecký"], ["CZ053", "Pardubický"], ["CZ063", "Vysočina"],
  ["CZ064", "Jihomoravský"], ["CZ071", "Olomoucký"], ["CZ072", "Zlínský"], ["CZ080", "Moravskoslezský"],
];
const STRATEGIE: Record<string, string> = {
  stavajici: "bránit a prohloubit stávající zákazníky", novi_zadavatele: "získat nové zadavatele",
  nove_obory: "vstoupit do sousedního oboru", vetsi_zakazky: "dostat se k větším zakázkám",
};
const VERT: Record<string, string> = {
  stavebnictvi: "Stavebnictví", it_sw: "IT a software", facility_sluzby: "Facility a služby",
  dodavky_zbozi: "Dodávky zboží", poradenstvi: "Poradenství", jine: "Jiný obor",
};

function AgentBadge({ a }: { a: AgentInfo | null }) {
  if (!a) return null;
  return a.rezim === "llm" || a.rezim === "claude"
    ? <span className="badge good" title={`${a.vstup_tokenu ?? "?"} vstupních / ${a.vystup_tokenu ?? "?"} výstupních tokenů`}>Agent: {a.poskytovatel ?? "AI"} ({a.model})</span>
    : <span className="badge neutral" title={a.duvod ? `Bez AI, podle pravidel z dat: ${a.duvod}` : "Bez AI, podle pravidel z dat"}>Agent: bez AI (pravidla)</span>;
}

// ------------------------------------------------------------------ prubeh dlouhych kroku
type Busy = { kde: "start" | "profil" | "ulozit"; kroky: string[] };
const KROKY_START = ["Hledám firmu v ARES", "Procházím přes 500 tisíc veřejných zakázek a Registr smluv",
  "Zjišťuji, s kým firma soutěží a kdo jsou její zákazníci", "Hledám obory, kde u jejích zákazníků vyhrává konkurence", "Připravuji otázky"];
const KROKY_PROFIL = ["Zpracovávám vaše odpovědi", "Sestavuji profil firmy", "Procházím zakázky za posledních 14 dní",
  "Hodnotím každou zakázku: obor, velikost, lhůta, konkurence"];
const KROKY_ULOZIT = ["Ukládám profil", "Znovu hodnotím zakázky podle upraveného profilu"];
const KROKY_HLEDANI = ["Hledám v databázi zakázek", "Ptám se ARES", "Kontroluji web firmy"];

export function Prubeh({ kroky, kompakt = false }: { kroky: string[]; kompakt?: boolean }) {
  const [t, setT] = useState(0);
  useEffect(() => {
    const t0 = Date.now();
    const id = window.setInterval(() => setT((Date.now() - t0) / 1000), 250);
    return () => window.clearInterval(id);
  }, [kroky]);
  const aktivni = Math.min(kroky.length - 1, Math.floor(t / 2.6));  // posledni krok zustane aktivni do konce
  return (
    <div id="prubeh" className={`prubeh ${kompakt ? "kompakt" : "card"}`} role="status" aria-live="polite">
      <div className="prubeh-bar"><span /></div>
      <ol className="prubeh-kroky">
        {kroky.map((k, i) => (
          <li key={k} className={i < aktivni ? "hotovo" : i === aktivni ? "bezi" : ""}>
            <span className="prubeh-ikona">{i < aktivni ? "✓" : i === aktivni ? <span className="spinner mini" /> : ""}</span>{k}
          </li>
        ))}
      </ol>
      <div className="small muted">{Math.floor(t)} s{t > 15 ? " · bezplatný server se po pauze probouzí, první načtení může trvat až minutu" : ""}</div>
    </div>
  );
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
  const [busy, setBusy] = useState<Busy | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    setRecon(null); setF1(null); setProfil(null); setZprav(null); setErr(null); setAgent1(null); setAgent2(null);
    if (!ico) return;
    setBusy({ kde: "start", kroky: ["Načítám uložený profil"] });
    api.onbStav(ico)
      .then((s) => {
        setRecon(s.recon); setF1(s.faze1); setOdp(s.odpovedi ?? {}); setProfil(s.profil); setZprav(s.zpravodaj ?? null);
      })
      .catch((e) => setErr(String(e.message ?? e)))
      .finally(() => setBusy(null));
  }, [ico]);

  const start = async (i: string, web: string) => {
    setErr(null); setBusy({ kde: "start", kroky: KROKY_START });
    setTimeout(() => document.getElementById("prubeh")?.scrollIntoView({ behavior: "smooth", block: "center" }), 50);
    try {
      const r = await api.onbStart(i, web);
      setRecon(r.recon); setF1(r.faze1); setAgent1(r.agent); setOdp({}); setProfil(null); setZprav(null);
      setTimeout(() => document.getElementById("recon")?.scrollIntoView({ behavior: "smooth", block: "start" }), 50);
      if (`#/onboarding/${r.recon.ico}` !== window.location.hash) window.history.replaceState(null, "", `#/onboarding/${r.recon.ico}`);
    } catch (e) {
      setErr(String((e as Error).message ?? e));
    } finally {
      setBusy(null);
    }
  };

  const dokoncit = async () => {
    if (!recon) return;
    setErr(null); setBusy({ kde: "profil", kroky: KROKY_PROFIL });
    setTimeout(() => document.getElementById("prubeh")?.scrollIntoView({ behavior: "smooth", block: "center" }), 50);
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
    setBusy({ kde: "ulozit", kroky: KROKY_ULOZIT });
    setTimeout(() => document.getElementById("prubeh")?.scrollIntoView({ behavior: "smooth", block: "center" }), 50);
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
          Zadejte IČO, název nebo web. Agent z otevřených zdrojů (ARES, ISVZ, Registr smluv, web) sestaví zpravodajský obraz firmy a jejích
          konkurentů, položí 6 otázek podložených daty, sestaví profil a hned ukáže zakázky, které firmu mají zajímat.
        </p>
      </div>
      <StartForm initial={ico ?? ""} onStart={start} disabled={!!busy} />
      {err && <div className="callout">{err}</div>}
      {busy?.kde === "start" && <Prubeh kroky={busy.kroky} />}
      {recon && f1 && <div id="recon"><ReconCard recon={recon} f1={f1} agent={agent1} /></div>}
      {recon && f1 && <Dotaznik f1={f1} odp={odp} setOdp={setOdp} onSubmit={dokoncit} disabled={!!busy} bezi={busy?.kde === "profil"} hotovo={!!profil} />}
      {busy?.kde === "profil" && <Prubeh kroky={busy.kroky} />}
      {profil && <ProfilCard profil={profil} agent={agent2} onSave={ulozit} disabled={!!busy} bezi={busy?.kde === "ulozit"} />}
      {busy?.kde === "ulozit" && <Prubeh kroky={busy.kroky} />}
      {zprav && profil && <ZpravodajCard z={zprav} profil={profil} />}
    </div>
  );
}

// ------------------------------------------------------------------ krok 0: firma (IČO, nazev nebo web)
function StartForm({ initial, onStart, disabled }: { initial: string; onStart: (ico: string, web: string) => void; disabled: boolean }) {
  const [q, setQ] = useState(initial);
  const [nalez, setNalez] = useState<NalezFirmy | null>(null);
  const [hledam, setHledam] = useState(false);
  const [chyba, setChyba] = useState<string | null>(null);
  const [seznam, setSeznam] = useState<{ ico: string; nazev: string | null; hotovo: boolean; vertical: string | null }[]>([]);
  useEffect(() => { setQ(initial); setNalez(null); }, [initial]);
  useEffect(() => { api.onbSeznam().then(setSeznam).catch(() => undefined); }, [initial]);

  const hledej = async () => {
    const t = q.trim();
    if (!t) return;
    setChyba(null); setHledam(true); setNalez(null);
    try {
      const r = await api.najdiFirmu(t);
      // jednoznacne IČO nebo IČO nalezene na webu -> rovnou spustit
      if (r.kandidati.length === 1 && (r.typ === "ico" || r.typ === "web") && !r.poznamka) onStart(r.kandidati[0].ico, r.web ?? "");
      else setNalez(r);
    } catch (e) {
      setChyba(String((e as Error).message ?? e));
    } finally {
      setHledam(false);
    }
  };

  return (
    <Card title="1. Firma" sub="Napište IČO, název firmy nebo adresu webu. Z webu si agent IČO dohledá sám (firmy ho musí na webu uvádět).">
      <form className="onb-start" onSubmit={(e) => { e.preventDefault(); hledej(); }}>
        <div className="search-field">
          <svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true"><circle cx="11" cy="11" r="7" fill="none" stroke="currentColor" strokeWidth="2" /><path d="m20 20-3.5-3.5" stroke="currentColor" strokeWidth="2" strokeLinecap="round" /></svg>
          <input className="field big" value={q} onChange={(e) => setQ(e.target.value)} autoFocus
            placeholder="např. 27082440, Strabag nebo www.alza.cz" aria-label="IČO, název firmy nebo web" />
        </div>
        <button className="btn primary big" disabled={disabled || hledam || !q.trim()}>
          {hledam || disabled ? <><span className="spinner mini light" /> Pracuji…</> : "Najít a spustit rešerši"}
        </button>
      </form>
      {hledam && <Prubeh kroky={KROKY_HLEDANI} kompakt />}
      {chyba && <div className="callout" style={{ marginTop: 12 }}>{chyba}</div>}
      {nalez && (
        <div className="kandidati">
          {nalez.poznamka && <div className="small secondary" style={{ marginBottom: 8 }}>{nalez.poznamka}</div>}
          {nalez.kandidati.length > 0 && <div className="small muted" style={{ marginBottom: 6 }}>Vyberte firmu:</div>}
          {nalez.kandidati.map((k) => (
            <button key={k.ico} type="button" className="kandidat" disabled={disabled} onClick={() => { setNalez(null); onStart(k.ico, nalez.web ?? ""); }}>
              <span className="kandidat-main">
                <b>{k.nazev ?? "(název neznámý)"}</b>
                <span className="small secondary">IČO {k.ico}{k.sidlo ? ` · ${k.sidlo}` : ""}</span>
              </span>
              <span className="kandidat-meta small">
                {k.vyhry > 0 && <span className="badge good">{num(k.vyhry)} výher</span>}
                {k.smluv_rs > 0 && <span className="badge neutral">{num(k.smluv_rs)} smluv</span>}
                <span className="muted">{k.zdroj}</span>
              </span>
            </button>
          ))}
        </div>
      )}
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
      {recon.ci && <CiBlok ci={recon.ci} />}
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

// ------------------------------------------------------------------ CI: klicova zjisteni + konkurenti
// vysoka sila = tezsi trh (cervena), nizka = prijemnejsi (zelena)
const SILA: Record<string, string> = { "vysoká": "bad", "střední": "warn", "nízká": "good" };
const JISTOTA: Record<string, string> = { "vysoká": "good", "střední": "warn", "nízká": "neutral" };

function Rating({ r }: { r: string }) {
  if (!r || r === "–") return null;
  return <span className="rating" title={`Admiralty kód: ${r[0]} = spolehlivost zdroje (A = zcela spolehlivý, oficiální registr), ${r.slice(1)} = věrohodnost informace (1 = potvrzeno)`}>{r}</span>;
}

const UROVEN: Record<string, number> = { "nízká": 1, "střední": 2, "vysoká": 3 };
const KRATCE: Record<string, string> = {
  "Rivalita mezi konkurenty": "Rivalita", "Síla odběratelů (zadavatelů)": "Síla zadavatelů", "Hrozba nových konkurentů": "Noví konkurenti",
  "Hrozba náhražek (substitutů)": "Náhražky", "Síla vašich dodavatelů": "Vaši dodavatelé",
};

/** Pavucinovy graf Porterovych 5 sil: 0 = stred, 1-3 = nizka/stredni/vysoka. Neohodnocene sily jsou "?" ve stredu. */
function PorterPavucina({ sily }: { sily: { sila: string; hodnoceni: string; text: string }[] }) {
  const W = 480, H = 290, cx = W / 2, cy = H / 2 + 8, R = 100;
  const n = sily.length;
  const bod = (i: number, v: number) => {
    const a = -Math.PI / 2 + (2 * Math.PI * i) / n;
    return [cx + Math.cos(a) * R * (v / 3), cy + Math.sin(a) * R * (v / 3)];
  };
  const hodnoty = sily.map((s) => UROVEN[s.hodnoceni] ?? 0);
  const poly = hodnoty.map((v, i) => bod(i, v).join(",")).join(" ");
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="pavucina" role="img" aria-label="Pavučinový graf Porterových pěti sil">
      {[1, 2, 3].map((k) => (
        <polygon key={k} points={sily.map((_, i) => bod(i, k).join(",")).join(" ")} fill="none" stroke="var(--grid)" strokeWidth={1} />
      ))}
      {sily.map((_, i) => { const [x, y] = bod(i, 3); return <line key={i} x1={cx} y1={cy} x2={x} y2={y} stroke="var(--grid)" strokeWidth={1} />; })}
      {[1, 2, 3].map((k) => (
        <text key={k} x={cx + 4} y={cy - (R * k) / 3 + 10} className="pav-osa">{["nízká", "střední", "vysoká"][k - 1]}</text>
      ))}
      <polygon points={poly} fill="var(--series-1)" fillOpacity={0.16} stroke="var(--series-1)" strokeWidth={2} strokeLinejoin="round" />
      {sily.map((s, i) => {
        const v = hodnoty[i];
        const [x, y] = bod(i, v);
        const [lx, ly] = bod(i, 3.55);
        return (
          <g key={s.sila}>
            {v > 0 && <circle cx={x} cy={y} r={5} fill="var(--series-1)" stroke="var(--surface-1)" strokeWidth={2}><title>{`${s.sila}: ${s.hodnoceni}`}</title></circle>}
            <text x={lx} y={ly} textAnchor={Math.abs(lx - cx) < 8 ? "middle" : lx > cx ? "start" : "end"} dominantBaseline="middle" className="pav-label">
              {KRATCE[s.sila] ?? s.sila}{v === 0 ? " ?" : ""}
              <title>{`${s.sila}: ${v ? s.hodnoceni : "zatím neohodnoceno – vyberte v seznamu vpravo"}`}</title>
            </text>
          </g>
        );
      })}
    </svg>
  );
}

function CiBlok({ ci }: { ci: CiAnalyza }) {
  const sb = ci.souboje.slice(0, 6);
  // sily, ktere z dat zmerit nejdou, ohodnoti uzivatel sam (oznacene jako "váš odhad", ne fakt)
  const [vlastni, setVlastni] = useState<Record<string, string>>({});
  const sily = (ci.porter?.sily ?? []).map((p) => (p.zdroj === "úvaha" && vlastni[p.sila] ? { ...p, hodnoceni: vlastni[p.sila] } : p));
  return (
    <div className="ci">
      {ci.zjisteni.length > 0 && (
        <div>
          <div className="ci-h">Klíčová zjištění</div>
          <ul className="zjisteni">
            {ci.zjisteni.map((z, i) => (
              <li key={i}>
                <span>{z.text}</span>
                <span className="zj-meta"><Zdroj z={z.zdroj} /> <Rating r={z.rating} />
                  <span className={`badge ${JISTOTA[z.jistota] ?? "neutral"}`} title="Jistota závěru podle velikosti vzorku">jistota {z.jistota}</span></span>
              </li>
            ))}
          </ul>
        </div>
      )}
      {sb.length > 0 && (
        <div>
          <div className="ci-h">Přímí soupeři <span className="muted small">(modrá = vaše výhry, oranžová = jejich; vpravo počet společných soutěží)</span></div>
          <div className="souboje">
            {sb.map((x) => {
              const tot = Math.max(1, x.my_vyhra + x.oni_vyhra);
              return (
                <a key={x.ico} className="souboj" href={`#/firma/${x.ico}`}>
                  <span className="souboj-nazev">{x.nazev}</span>
                  <span className="souboj-bar" title={`${x.my_vyhra} : ${x.oni_vyhra}`}>
                    <span className="my" style={{ width: `${(100 * x.my_vyhra) / tot}%` }} />
                    <span className="oni" style={{ width: `${(100 * x.oni_vyhra) / tot}%` }} />
                  </span>
                  <span className="small num">{x.my_vyhra}:{x.oni_vyhra} <span className="muted">/ {num(x.stretu)}×</span></span>
                </a>
              );
            })}
          </div>
        </div>
      )}
      {ci.porter && (
        <div className="ci-full">
          <div className="ci-h" title="Model Michaela Portera: pět sil, které určují, jak těžké je v oboru vydělávat.">
            Porterových 5 sil v oboru {ci.porter.obor.toLowerCase()} <span className="muted small">(čím dál od středu, tím tvrdší trh)</span>
          </div>
          <div className="porter-grid">
            <PorterPavucina sily={sily} />
            <ul className="porter">
              {sily.map((p) => (
                <li key={p.sila}>
                  <span className={`badge ${SILA[p.hodnoceni] ?? "neutral"}`}>{p.zdroj === "úvaha" && vlastni[p.sila] ? `${p.hodnoceni} (váš odhad)` : p.hodnoceni}</span>
                  <span><b>{p.sila}.</b> {p.text}{" "}
                    {p.zdroj === "úvaha" ? (
                      <span className="row" style={{ gap: 4, marginTop: 4 }}>
                        <span className="muted small">Jak to vidíte vy?</span>
                        {["nízká", "střední", "vysoká"].map((u) => (
                          <button key={u} type="button" className={`chip btnchip ${vlastni[p.sila] === u ? "on" : ""}`}
                            onClick={() => setVlastni({ ...vlastni, [p.sila]: vlastni[p.sila] === u ? "" : u })}>{u}</button>
                        ))}
                      </span>
                    ) : <Zdroj z={p.zdroj} />}</span>
                </li>
              ))}
            </ul>
          </div>
        </div>
      )}
    </div>
  );
}

// ------------------------------------------------------------------ krok 2: otazky
function Dotaznik({ f1, odp, setOdp, onSubmit, disabled, bezi, hotovo }: {
  f1: Faze1; odp: Record<string, Odpoved>; setOdp: (o: Record<string, Odpoved>) => void; onSubmit: () => void; disabled: boolean; bezi: boolean; hotovo: boolean;
}) {
  const toggle = (qid: string, val: string, multi: boolean) => {
    const cur = odp[qid] ?? { vybrano: [], text: "" };
    const has = cur.vybrano.includes(val);
    const vybrano = multi ? (has ? cur.vybrano.filter((x) => x !== val) : [...cur.vybrano, val]) : (has ? [] : [val]);
    setOdp({ ...odp, [qid]: { ...cur, vybrano } });
  };
  const odpovezeno = f1.questions.filter((q) => (odp[q.id]?.vybrano.length ?? 0) > 0 || (odp[q.id]?.text ?? "").trim()).length;
  return (
    <Card title={`3. ${f1.questions.length} otázek k vaší firmě`} sub="U každé otázky vidíte, z jakých dat vychází a k čemu odpověď poslouží. Klikněte na možnost nebo napište vlastní. Co nevyplníte, doplním podle dosavadních zakázek firmy.">
      <div className="grid" style={{ gap: 18 }}>
        {f1.questions.map((q, i) => (
          <div key={q.id} className="otazka">
            <div className="small muted">{i + 1}. {q.category}</div>
            <div className="otazka-text">{q.question_text}</div>
            <div className="small secondary" style={{ marginTop: 2 }}>{q.allow_multiple ? "Můžete vybrat víc možností." : "Vyberte jednu možnost."}</div>
            {(q.evidence?.length ?? 0) > 0 && <Dukazy ev={q.evidence as Dukaz[]} />}
            {q.proc && <div className="small secondary proc"><b>Proč se ptáme:</b> {q.proc}</div>}
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
        <button className="btn primary" disabled={disabled} onClick={onSubmit}>
          {bezi ? <><span className="spinner mini light" /> Sestavuji…</> : hotovo ? "Znovu sestavit profil" : "Sestavit profil a zpravodaj"}
        </button>
        <span className="small muted">zodpovězeno {odpovezeno} z {f1.questions.length}</span>
      </div>
    </Card>
  );
}

function Zdroj({ z }: { z: string }) {
  const { text, title } = zdrojLidsky(z);
  return <span className="muted small" title={title || undefined} style={title ? { textDecoration: "underline dotted", cursor: "help" } : undefined}>zdroj: {text}</span>;
}

function Dukazy({ ev }: { ev: Dukaz[] }) {
  return (
    <ul className="dukazy">
      {ev.map((e, i) => (
        <li key={i}><span>{e.text}</span> {e.zdroj !== "–" && <Zdroj z={e.zdroj} />} <Rating r={e.rating} /></li>
      ))}
    </ul>
  );
}

// ------------------------------------------------------------------ krok 3: profil
const seznamText = (xs: string[]) => xs.join(", ");

function Obory({ kody }: { kody: string[] }) {
  const obory = [...new Set(kody.map(oborKodu))];
  if (!obory.length) return null;
  return <div className="row" style={{ gap: 4, marginTop: 4 }}>{obory.map((o) => <span key={o} className="chip">{o}</span>)}</div>;
}
const zText = (s: string) => s.split(/[,;\n]/).map((x) => x.trim()).filter(Boolean);

function ProfilCard({ profil, agent, onSave, disabled, bezi }: { profil: Profil2; agent: AgentInfo | null; onSave: (p: Profil2) => void; disabled: boolean; bezi: boolean }) {
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
      <Card title="4. Profil firmy" sub="Podle tohoto profilu se filtrují a hodnotí zakázky. Cokoli upravte a klikněte Uložit – zpravodaj se přepočítá."
        right={<div className="row" style={{ gap: 6 }}><span className="badge neutral">{VERT[p.vertical] ?? p.vertical}</span><AgentBadge a={agent} /></div>}>
        <label className="lbl">Popis kompetencí (z něj se počítá textová podobnost se zakázkami)</label>
        <textarea className="field" rows={3} value={p.core_capabilities_description} onChange={(e) => set({ core_capabilities_description: e.target.value })} />
        <div className="grid g2" style={{ marginTop: 10 }}>
          <div>
            <label className="lbl" title={CPV_VYSVETLENI}>Hlavní obory zakázek <span className="muted" style={{ textDecoration: "underline dotted", cursor: "help" }}>(kódy CPV)</span></label>
            <input className="field mono" value={seznamText(p.cpv_codes.main)} onChange={(e) => set({ cpv_codes: { ...p.cpv_codes, main: zText(e.target.value) } })} />
            <Obory kody={p.cpv_codes.main} />
            {p.cpv_zdroj && <div className="small muted" style={{ marginTop: 2 }}>{p.cpv_zdroj}</div>}
            <label className="lbl" title={CPV_VYSVETLENI}>Další obory, které vás mohou zajímat (kódy CPV)</label>
            <input className="field mono" value={seznamText(p.cpv_codes.secondary)} onChange={(e) => set({ cpv_codes: { ...p.cpv_codes, secondary: zText(e.target.value) } })} />
            <Obory kody={p.cpv_codes.secondary} />
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
            <p className="small secondary" style={{ margin: "4px 0 0" }}>Obrat slouží k odhadu, zda firma splní kvalifikaci (zadavatel smí chtít nejvýš 2× hodnotu zakázky). Bez něj se počítá s tržbami od státu ze soutěží a z Registru smluv.</p>
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
            <label className="lbl">Kraje, kde chcete zakázky</label>
            <div className="row" style={{ gap: 6, marginTop: 4 }}>
              <button type="button" className={`chip btnchip ${cela ? "on" : ""}`} onClick={() => set({ regions_nuts3: ["CZ0"] })}>Celá ČR</button>
              {KRAJE.map(([k, n]) => (
                <button key={k} type="button" className={`chip btnchip ${!cela && p.regions_nuts3.includes(k) ? "on" : ""}`} onClick={() => toggleKraj(k)} title={k}>{n}</button>
              ))}
            </div>
            <div className="row small" style={{ marginTop: 10, gap: 14 }}>
              <label><input type="checkbox" checked={p.budget.vzmr_interest} onChange={(e) => set({ budget: { ...p.budget, vzmr_interest: e.target.checked } })} /> i malé zakázky (zakázky malého rozsahu)</label>
              {p.cooperation_model && <span className="secondary">způsob dodání: {p.cooperation_model === "bodyshopping" ? "pronájem vlastních lidí" : p.cooperation_model}</span>}
            </div>
            <label className="lbl">Co zakázku vyřadí</label>
            <ul className="small secondary" style={{ margin: "4px 0 0", paddingLeft: 18 }}>{p.dealbreakers.map((d) => <li key={d}>{d}</li>)}</ul>
            <div className="small muted" style={{ marginTop: 6 }}>Dosavadní zákazníci, jejichž zakázky dám výš: {p.whitelist_procurer_icos.length}</div>
            {p.strategy && <div className="small" style={{ marginTop: 6 }}><span className="muted">Strategický cíl:</span> <b>{STRATEGIE[p.strategy]}</b></div>}
            {(p.watchlist?.length ?? 0) > 0 && (
              <div className="row small" style={{ marginTop: 6, gap: 6 }}>
                <span className="muted">Sledovaní konkurenti:</span>
                {p.watchlist!.map((w) => <a key={w.ico} className="chip" href={`#/firma/${w.ico}`}>{w.nazev ?? w.ico}</a>)}
              </div>
            )}
          </div>
        </div>
        <div className="row" style={{ marginTop: 14 }}>
          <button className="btn primary" disabled={disabled} onClick={() => onSave(p)}>
            {bezi ? <><span className="spinner mini light" /> Přepočítávám…</> : "Uložit a přepočítat zpravodaj"}
          </button>
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
      {shown.length === 0 && <div className="empty">Nic tu není. Zkuste v profilu přidat obory nebo kraje.</div>}
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
                {((p.sledovani?.length ?? 0) > 0 || p.cil) && (
                  <span className="row" style={{ gap: 6, marginTop: 4 }}>
                    {p.cil && <span className="badge good">cíl: {p.cil}</span>}
                    {p.sledovani?.slice(0, 2).map((w) => (
                      <span key={w.ico} className="badge warn" title="Sledovaný konkurent u tohoto zadavatele už vyhrál">⚑ {w.nazev} tu vyhrál {w.vyher}×</span>
                    ))}
                  </span>
                )}
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
