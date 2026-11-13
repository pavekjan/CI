import { useEffect, useRef, useState } from "react";
import { adminHeslo, api, nastavAdminHeslo, type AiForm, type AiLimity, type Beh, type Nastaveni, type Stav } from "../api";
import { Card, Kpi } from "../components";
import { datum, mesic, num } from "../format";

export default function Data({ stav, refresh }: { stav: Stav | null; refresh: () => void }) {
  const [beh, setBeh] = useState<Beh | null>(null);
  const [diag, setDiag] = useState<string | null>(null);
  const [diagIco, setDiagIco] = useState("00177041");
  const [copied, setCopied] = useState(false);
  const runDiag = async () => {
    setDiag("Načítám… (prochází stažené soubory, může to trvat i minutu)");
    try {
      setDiag(JSON.stringify(await api.diagnostika(diagIco.trim() || undefined), null, 2));
    } catch (e) {
      setDiag(String(e));
    }
  };
  const copy = async () => {
    if (!diag) return;
    try {
      await navigator.clipboard.writeText(diag);
    } catch {
      const ta = document.createElement("textarea");
      ta.value = diag;
      document.body.appendChild(ta);
      ta.select();
      document.execCommand("copy");
      ta.remove();
    }
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };
  const logRef = useRef<HTMLDivElement>(null);
  const [nast, setNast] = useState<Nastaveni | null>(null);
  const [vault, setVault] = useState("");
  const [exaKey, setExaKey] = useState("");
  const [ulozeno, setUlozeno] = useState(false);
  const [chybaUlozeni, setChybaUlozeni] = useState<string | null>(null);
  const [heslo, setHeslo] = useState(adminHeslo());
  const [chybaAkt, setChybaAkt] = useState<string | null>(null);
  const nactiNast = () => api.nastaveni().then((n) => { setNast(n); setVault(n.obsidian_vault); }).catch(() => undefined);
  useEffect(() => { nactiNast(); }, []);
  const prihlasit = async () => {
    nastavAdminHeslo(heslo.trim());
    await nactiNast();
  };
  const ulozit = async () => {
    setChybaUlozeni(null);
    let n: Nastaveni;
    try {
      n = await api.ulozNastaveni({ obsidian_vault: vault, ...(exaKey ? { exa_api_key: exaKey } : {}) });
    } catch (e) {
      setChybaUlozeni(String(e instanceof Error ? e.message : e));
      return;
    }
    setNast(n);
    setExaKey("");
    setUlozeno(true);
    setTimeout(() => setUlozeno(false), 2000);
  };

  useEffect(() => {
    let alive = true;
    const tick = async () => {
      try {
        const b = await api.beh();
        if (!alive) return;
        setBeh((prev) => {
          if (prev?.bezi && !b.bezi) refresh();
          return b;
        });
      } catch {
        /* server mozna nebezi */
      }
    };
    tick();
    const t = setInterval(tick, 1500);
    return () => { alive = false; clearInterval(t); };
  }, [refresh]);

  useEffect(() => {
    if (logRef.current) logRef.current.scrollTop = logRef.current.scrollHeight;
  }, [beh?.log.length]);

  const start = async (rezim: "rychle" | "plny") => {
    setChybaAkt(null);
    try {
      await api.aktualizovat(rezim);
    } catch (e) {
      setChybaAkt(String(e instanceof Error ? e.message : e));
    }
    setBeh(await api.beh());
  };

  return (
    <div className="grid">
      <h1>Data</h1>
      {stav && (
        <div className="grid g4">
          <Kpi label="Zakázek" value={num(stav.zakazek)} note={stav.od ? `${datum(stav.od)} – ${datum(stav.do)}` : "zatím nic"} />
          <Kpi label="Dodavatelů" value={num(stav.dodavatelu)} />
          <Kpi label="Smluv (Registr smluv)" value={num(stav.smluv)} note={stav.obdobi?.rs_od ? `${mesic(stav.obdobi.rs_od)} – ${mesic(stav.obdobi.rs_do!)}` : undefined} />
          <Kpi label="Profilů z ARES" value={num(stav.firem_ares)} />
        </div>
      )}

      {nast?.verejne && (
        <Card title="Online verze" sub="Tahle kopie běží veřejně na internetu. Prohlížet, hledat firmy a dělat onboarding může kdokoli. Aktualizaci dat, klíče a diagnostiku spustí jen správce s heslem.">
          <div className="row">
            <input className="field" style={{ width: 220, marginTop: 0 }} type="password" value={heslo} onChange={(e) => setHeslo(e.target.value)} placeholder="admin heslo" aria-label="Admin heslo" />
            <button className="btn primary" onClick={prihlasit}>Přihlásit</button>
            {nast.admin ? <span className="badge good">✓ správce</span> : adminHeslo() ? <span className="badge bad">špatné heslo</span> : <span className="secondary small">jen prohlížení</span>}
          </div>
        </Card>
      )}

      {stav?.verejne && !stav.demo ? (
      <Card title="Aktualizace dat" sub="Online verze si data nestahuje sama: server zakázek (ISVZ) cloudové servery neobsluhuje.">
        <p className="small" style={{ marginTop: 0 }}>
          Data se aktualizují <b>každé ráno automaticky</b> přes GitHub (záložka Actions → <i>Aktualizace dat</i>), nebo
          správce na svém počítači spustí <code>aktualizovat_online.bat</code>. Online verze si nová data načte při
          dalším startu (po uspání, nebo na Renderu <i>Manual Deploy → Restart service</i>).
        </p>
        <p className="secondary small" style={{ marginBottom: 0 }}>
          {stav.do ? <>Zakázky jsou do {datum(stav.do)}. Stát je zveřejňuje po měsících, Registr smluv denně.</> : "Data se právě připravují."}
        </p>
      </Card>
      ) : (
      <Card title="Aktualizace dat" sub="Agenti stáhnou otevřená data státu, vytáhnou z nich zakázky, zkontrolují je a přepočítají index firem.">
        {stav?.demo && <div className="callout" style={{ marginBottom: 12 }}>Běžíte v DEMO režimu: aktualizace jen znovu vygeneruje umělá data. Pro reálná data spusťte aplikaci volbou „Aplikace – reálná data“.</div>}
        <div className="row">
          <button className="btn primary" disabled={beh?.bezi} onClick={() => start("rychle")}>Rychlá aktualizace</button>
          <span className="secondary small">poslední 3 měsíce, bez Registru smluv (proto tam je 0 smluv) · zhruba 1–3 min na měsíc</span>
        </div>
        <div className="row" style={{ marginTop: 10 }}>
          <button className="btn" disabled={beh?.bezi} onClick={() => start("plny")}>Plná aktualizace</button>
          <span className="secondary small">12 měsíců + Registr smluv (ověření vítězů) · první běh desítky minut, další jen přírůstky</span>
        </div>
        {chybaAkt && <div className="callout" style={{ marginTop: 12 }}>{chybaAkt}</div>}
        {beh && (beh.bezi || beh.log.length > 0) && (
          <div style={{ marginTop: 16 }}>
            <div className="row" style={{ marginBottom: 8 }}>
              {beh.bezi ? <><span className="spinner" /> <b>Probíhá…</b></> : beh.chyba ? <span className="badge bad">✕ chyba: {beh.chyba}</span> : <span className="badge good">✓ hotovo</span>}
            </div>
            <div className="log" ref={logRef}>{beh.log.join("\n")}</div>
          </div>
        )}
      </Card>
      )}

      {nast && <AiCard key={`${nast.admin}-${nast.ai.poskytovatel}`} nast={nast} onSaved={setNast} />}

      <Card title="Obsidian a Exa" sub="Pro export do Obsidianu (knowledge graph). Vše je nepovinné.">
        <label className="small secondary" htmlFor="vault">Cesta ke složce Obsidian trezoru (vytvoří se v ní podsložka TenderScope)</label>
        <input id="vault" className="field" value={vault} onChange={(e) => setVault(e.target.value)} placeholder="např. C:\Users\Jan\OneDrive\9.semestr\CI\Obsidian\Jan" />
        <label className="small secondary" htmlFor="exa" style={{ marginTop: 10, display: "block" }}>
          Exa API klíč (nepovinné – dohledá k firmě zdroje z webu; klíč na dashboard.exa.ai) {nast?.exa_api_key_nastaven && <span className="badge good">✓ nastaven {nast.exa_api_key_nahled}</span>}
        </label>
        <input id="exa" className="field" type="password" value={exaKey} onChange={(e) => setExaKey(e.target.value)} placeholder={nast?.exa_api_key_nastaven ? "ponechat stávající" : "nevyplněno"} />
        <div className="row" style={{ marginTop: 12 }}>
          <button className="btn primary" onClick={ulozit}>Uložit</button>
          {ulozeno && <span className="badge good">✓ uloženo</span>}
          {chybaUlozeni && <span className="badge bad">{chybaUlozeni}</span>}
        </div>
      </Card>

      <Card title="Diagnostika" sub="Když něco nesedí (chybí ceny, CPV, vítězové): zadejte IČO firmy, u které to vidíte, klikněte, zkopírujte výpis a pošlete ho. Ukáže skutečný záznam z dat a co z něj program vyčetl.">
        <div className="row">
          <input className="field" style={{ width: 160, marginTop: 0 }} value={diagIco} onChange={(e) => setDiagIco(e.target.value)} placeholder="IČO firmy (nepovinné)" title="Najde v datech záznam s tímto IČO (výchozí: Škoda Auto)" />
          <button className="btn" onClick={runDiag}>Spustit diagnostiku</button>
          {diag && !diag.startsWith("Načítám") && <button className="btn primary" onClick={copy}>{copied ? "✓ Zkopírováno" : "Kopírovat výpis"}</button>}
        </div>
        {diag && <div className="log" style={{ marginTop: 12 }}>{diag}</div>}
      </Card>

      <Card title="Zdroje">
        <div className="table-wrap">
          <table>
            <thead><tr><th>Zdroj</th><th>Registrace</th><th>Co z něj bereme</th></tr></thead>
            <tbody>
              <tr><td>Registr veřejných zakázek – open data ISVZ (NEN, Věstník, Tender arena, TENDERMARKET)</td><td>ne</td><td>zakázky, CPV, hodnoty, lhůty, účastníci, vítězové, ceny</td></tr>
              <tr><td>Registr smluv – open data</td><td>ne</td><td>skutečně uzavřené smlouvy, křížové ověření vítězů</td></tr>
              <tr><td>ARES</td><td>ne</td><td>název, sídlo, NACE, vznik/zánik firmy</td></tr>
              <tr><td>Google News RSS</td><td>ne</td><td>zprávy o firmě</td></tr>
            </tbody>
          </table>
        </div>
      </Card>
    </div>
  );
}


// ------------------------------------------------------------------ vyber AI poskytovatele
function AiCard({ nast, onSaved }: { nast: Nastaveni; onSaved: (n: Nastaveni) => void }) {
  const ai = nast.ai;
  const [prov, setProv] = useState(ai.poskytovatel);
  const p = ai.poskytovatele.find((x) => x.id === prov) ?? ai.poskytovatele[0];
  const [klic, setKlic] = useState("");
  const [model, setModel] = useState(p.model);
  const [url, setUrl] = useState(p.url);
  const [ucet, setUcet] = useState(p.ucet);
  const [limit, setLimit] = useState<string>(nast.limity?.ai_limit_nastaveny == null ? "" : String(nast.limity.ai_limit_nastaveny));
  const [modely, setModely] = useState<string[]>([]);
  const [zprava, setZprava] = useState<{ ok: boolean; text: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const zamceno = !!nast.verejne && !nast.admin;

  const zmenProv = (id: string) => {
    const q = ai.poskytovatele.find((x) => x.id === id)!;
    setProv(id); setKlic(""); setModel(q.model); setUrl(q.url); setUcet(q.ucet); setModely([]); setZprava(null);
  };
  const form = (): AiForm => ({
    llm_poskytovatel: prov, ...(klic ? { llm_klic: klic } : {}), ...(model ? { llm_model: model } : {}),
    ...(p.vlastni_url ? { llm_url: url } : {}), ...(p.potrebuje_ucet && ucet ? { llm_ucet: ucet } : {}),
  });
  const akce = async (fn: () => Promise<void>) => {
    setBusy(true); setZprava(null);
    try { await fn(); } catch (e) { setZprava({ ok: false, text: String(e instanceof Error ? e.message : e) }); }
    setBusy(false);
  };
  const nacistModely = () => akce(async () => {
    const r = await api.aiModely(form());
    if (r.ok && r.modely) { setModely(r.modely); setZprava({ ok: true, text: `Načteno ${r.modely.length} modelů – vyberte v poli Model.` }); }
    else setZprava({ ok: false, text: r.chyba || "Modely se nepodařilo načíst." });
  });
  const vyzkouset = () => akce(async () => {
    const r = await api.aiTest(form());
    setZprava(r.ok ? { ok: true, text: `Funguje ✓ ${r.poskytovatel} (${r.model}) odpověděl: „${r.odpoved}“` } : { ok: false, text: r.chyba || "Nefunguje." });
  });
  const ulozit = () => akce(async () => {
    const n = await api.ulozNastaveni({ ...form(), ai_denni_limit: limit.trim() === "" ? null : limit.trim() });
    onSaved(n); setKlic("");
    setZprava({ ok: true, text: "Uloženo. Onboarding teď používá " + (n.ai.pripraveno ? `${p.nazev} (${n.ai.model}).` : "pravidla – chybí klíč.") });
  });

  return (
    <Card title="Umělá inteligence (onboarding agent)"
      sub="Vyberte, která AI píše otázky a profil firmy. Klíč zůstává jen u vás (na GitHub se nenahrává). Bez AI onboarding funguje na pravidla.">
      <div className="row" style={{ marginBottom: 8 }}>
        {ai.pripraveno ? <span className="badge good">Aktivní: {ai.poskytovatele.find((x) => x.id === ai.poskytovatel)?.nazev} · {ai.model}</span>
          : <span className="badge neutral">AI není nastavená – používají se pravidla</span>}
        {nast.limity && <span className="secondary small">dnes {nast.limity.ai_dnes} {nast.limity.ai_max == null ? "volání AI (bez denního limitu)" : `/ ${nast.limity.ai_max} volání AI`}</span>}
      </div>
      {ai.pripraveno && !zamceno && <LimityAI />}
      {zamceno && <div className="callout" style={{ marginBottom: 10 }}>Na online verzi mění AI jen správce (přihlášení výše). Návštěvníci mají onboarding na pravidla, nic se neplatí.</div>}
      <label className="small secondary" htmlFor="ai-prov">Poskytovatel</label>
      <select id="ai-prov" className="field" value={prov} onChange={(e) => zmenProv(e.target.value)} disabled={zamceno}>
        {([["Placené (podle spotřeby)", (x: typeof p) => !x.zdarma && !x.vlastni_url],
           ["Zdarma (bezplatné tarify)", (x: typeof p) => x.zdarma && !x.vlastni_url],
           ["Na vašem počítači / vlastní", (x: typeof p) => x.vlastni_url]] as const).map(([nazev, f]) => (
          <optgroup key={nazev} label={nazev}>
            {ai.poskytovatele.filter(f).map((x) => (
              <option key={x.id} value={x.id}>{x.nazev}{!x.potrebuje_klic && x.zdarma ? " · bez klíče" : ""}{x.klic_nastaven ? " ✓" : ""}</option>
            ))}
          </optgroup>
        ))}
      </select>
      {(p.limit || p.pozn || p.zdarma) && (
        <div className="callout small" style={{ marginTop: 8 }}>
          {p.limit && <div><b>Limit:</b> {p.limit}</div>}
          <div><b>Klíč:</b> {p.potrebuje_klic ? "nutný" : p.ma_klic_pole ? "není nutný (s klíčem vyšší limity)" : "nepotřebuje"}{p.potrebuje_ucet ? " + Account ID" : ""}</div>
          {p.pozn && <div style={{ marginTop: 4 }}>{p.pozn}</div>}
          {p.zdarma && !p.soukromi_ok && (
            <div style={{ marginTop: 6 }}>
              ⚠️ <b>Soukromí:</b> bezplatné tarify mohou dotazy ukládat nebo je použít ke zlepšování modelů. Onboarding posílá
              údaje o firmě a vaše odpovědi z dotazníku – nepište tam nic důvěrného. Pro citlivá data použijte placený tarif nebo Ollamu.
            </div>
          )}
        </div>
      )}
      {p.ma_klic_pole && (
        <>
          <label className="small secondary" htmlFor="ai-klic" style={{ marginTop: 10, display: "block" }}>
            API klíč {p.potrebuje_klic ? "" : "(nepovinné)"} {p.web && <a href={p.web} target="_blank" rel="noopener noreferrer">kde ho získat</a>}
            {p.klic_nastaven && <span className="badge good" style={{ marginLeft: 6 }}>✓ uložen {p.klic_nahled}</span>}
          </label>
          <input id="ai-klic" className="field" type="password" autoComplete="off" value={klic} onChange={(e) => setKlic(e.target.value)}
            placeholder={p.klic_nastaven ? "ponechat stávající" : "vložte klíč"} disabled={zamceno} />
        </>
      )}
      {prov === "anthropic" && !ai.anthropic_sdk && <div className="badge warn" style={{ marginTop: 6 }}>chybí knihovna anthropic – spusťte znovu TenderScope.bat</div>}
      {prov === "ollama" && <div className="small muted" style={{ marginTop: 6 }}>Ollama běží zdarma na vašem počítači: nainstalujte ji z ollama.com a stáhněte model (např. příkazem <code>ollama pull llama3.1</code>). Na online verzi nefunguje.</div>}
      {p.potrebuje_ucet && (
        <>
          <label className="small secondary" htmlFor="ai-ucet" style={{ marginTop: 10, display: "block" }}>Account ID (32 znaků, v přehledu účtu Cloudflare vpravo)</label>
          <input id="ai-ucet" className="field" value={ucet} onChange={(e) => setUcet(e.target.value.trim())} placeholder="např. 0123456789abcdef0123456789abcdef" disabled={zamceno} />
        </>
      )}
      {p.vlastni_url && (
        <>
          <label className="small secondary" htmlFor="ai-url" style={{ marginTop: 10, display: "block" }}>Adresa API (OpenAI-kompatibilní, končí obvykle /v1)</label>
          <input id="ai-url" className="field" value={url} onChange={(e) => setUrl(e.target.value)} placeholder="https://…/v1" disabled={zamceno} />
        </>
      )}
      <label className="small secondary" htmlFor="ai-model" style={{ marginTop: 10, display: "block" }}>
        Model {p.model_vychozi && <span className="muted">(návrh: {p.model_vychozi} – názvy se mění, tlačítkem „Načíst modely“ zjistíte aktuální)</span>}
      </label>
      <input id="ai-model" className="field" list="ai-modely" value={model} onChange={(e) => setModel(e.target.value)} placeholder="název modelu" disabled={zamceno} />
      <datalist id="ai-modely">{modely.map((m) => <option key={m} value={m} />)}</datalist>
      <label className="small secondary" htmlFor="ai-limit" style={{ marginTop: 10, display: "block" }}>
        Denní limit volání AI <span className="muted">(prázdné = výchozí: {p.zdarma ? "u bezplatných bez limitu" : "30 u placených"}; 0 = bez limitu)</span>
      </label>
      <input id="ai-limit" className="field" style={{ maxWidth: 160 }} inputMode="numeric" value={limit}
        onChange={(e) => setLimit(e.target.value.replace(/[^0-9]/g, ""))} placeholder={p.zdarma ? "bez limitu" : "30"}
        disabled={zamceno || !!nast.limity?.ai_limit_env} />
      {nast.limity?.ai_limit_env && <div className="small muted">Limit je nastavený na serveru proměnnou TS_AI_DENNI_LIMIT.</div>}
      <div className="small muted" style={{ marginTop: 4 }}>Když poskytovatel zdarma vyčerpá svůj vlastní limit (např. OpenRouter free 50 dotazů/den), onboarding se nezastaví – přepne se na pravidla a ukáže proč.</div>
      <div className="row" style={{ marginTop: 12 }}>
        <button className="btn primary" onClick={ulozit} disabled={busy || zamceno}>Uložit a používat</button>
        <button className="btn" onClick={nacistModely} disabled={busy || zamceno}>Načíst modely</button>
        <button className="btn" onClick={vyzkouset} disabled={busy || zamceno} title="Pošle krátký zkušební dotaz (pár haléřů)">Vyzkoušet</button>
        {busy && <span className="spinner" />}
      </div>
      {zprava && <div className={`badge ${zprava.ok ? "good" : "bad"}`} style={{ marginTop: 10, whiteSpace: "normal" }}>{zprava.text}</div>}
    </Card>
  );
}

function LimityAI() {
  const [l, setL] = useState<AiLimity | null>(null);
  const [busy, setBusy] = useState(false);
  const nacist = () => { setBusy(true); api.aiLimity().then(setL).catch(() => setL(null)).finally(() => setBusy(false)); };
  useEffect(nacist, []);
  if (!l) return <div className="small muted" style={{ marginBottom: 8 }}>{busy ? "Zjišťuji limity poskytovatele…" : ""}</div>;
  if (!l.ok) return null;
  const d = l.limity ?? {};
  const casti = [d.rpm && `${d.rpm}/min`, d.rph && `${d.rph}/hod`, d.rpd && `${d.rpd}/den`, d.mesicne && `${d.mesicne}/měsíc`,
    d.tpm && `${num(d.tpm)} tokenů/min`, d.tpd && `${num(d.tpd)} tokenů/den`, d.soubezne && `${d.soubezne} souběžný dotaz`].filter(Boolean);
  return (
    <div className="callout small" style={{ marginBottom: 10 }}>
      <div><b>Limity poskytovatele:</b> {casti.join(", ") || "—"}{d.pozn ? ` (${d.pozn})` : ""}
        {d.zdroj && <> · <a href={d.zdroj} target="_blank" rel="noreferrer">zdroj</a></>}</div>
      {l.zivy?.denni_zbyva != null && <div><b>Zbývá dnes (živě z OpenRouteru):</b> {l.zivy.denni_zbyva} z {l.zivy.denni_limit} dotazů zdarma</div>}
      {l.zivy?.kredit_zbyva != null && <div><b>Zbývající kredit klíče:</b> {l.zivy.kredit_zbyva}</div>}
      {l.hlavicky?.zbyva_dotazu != null && <div><b>Poskytovatel hlásí:</b> zbývá {l.hlavicky.zbyva_dotazu}{l.hlavicky.limit_dotazu ? ` z ${l.hlavicky.limit_dotazu}` : ""} dotazů{l.hlavicky.zbyva_tokenu != null ? `, ${num(l.hlavicky.zbyva_tokenu)} tokenů` : ""}</div>}
      <div>Tato aplikace dnes: {l.dnes ?? 0} dotazů (za poslední minutu {l.za_minutu ?? 0}){l.aplikace?.max ? ` · vlastní strop ${l.aplikace.max}/den` : " · vlastní strop: bez limitu"}</div>
      {l.pauza && <div className="warn-text"><b>AI je teď pozastavená:</b> {l.pauza.duvod}, znovu za {l.pauza.zbyva}. Onboarding mezitím jede na pravidla.</div>}
      <button className="btn" style={{ marginTop: 6 }} onClick={nacist} disabled={busy}>Obnovit</button>
    </div>
  );
}
