import { useEffect, useRef, useState } from "react";
import { api, type Beh, type Nastaveni, type Stav } from "../api";
import { Card, Kpi } from "../components";
import { datum, num } from "../format";

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
  const [claudeKey, setClaudeKey] = useState("");
  const [ulozeno, setUlozeno] = useState(false);
  useEffect(() => {
    api.nastaveni().then((n) => { setNast(n); setVault(n.obsidian_vault); }).catch(() => undefined);
  }, []);
  const ulozit = async () => {
    const n = await api.ulozNastaveni({ obsidian_vault: vault, ...(exaKey ? { exa_api_key: exaKey } : {}), ...(claudeKey ? { anthropic_api_key: claudeKey } : {}) });
    setNast(n);
    setExaKey("");
    setClaudeKey("");
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
    await api.aktualizovat(rezim);
    setBeh(await api.beh());
  };

  return (
    <div className="grid">
      <h1>Data</h1>
      {stav && (
        <div className="grid g4">
          <Kpi label="Zakázek" value={num(stav.zakazek)} note={stav.od ? `${datum(stav.od)} – ${datum(stav.do)}` : "zatím nic"} />
          <Kpi label="Dodavatelů" value={num(stav.dodavatelu)} />
          <Kpi label="Smluv (Registr smluv)" value={num(stav.smluv)} />
          <Kpi label="Profilů z ARES" value={num(stav.firem_ares)} />
        </div>
      )}

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
        {beh && (beh.bezi || beh.log.length > 0) && (
          <div style={{ marginTop: 16 }}>
            <div className="row" style={{ marginBottom: 8 }}>
              {beh.bezi ? <><span className="spinner" /> <b>Probíhá…</b></> : beh.chyba ? <span className="badge bad">✕ chyba: {beh.chyba}</span> : <span className="badge good">✓ hotovo</span>}
            </div>
            <div className="log" ref={logRef}>{beh.log.join("\n")}</div>
          </div>
        )}
      </Card>

      <Card title="Klíče a Obsidian" sub="Claude API pohání Onboarding agenta (otázky a profil firmy). Exa a Obsidian slouží pro knowledge graph. Vše je nepovinné.">
        <label className="small secondary" htmlFor="claude">
          Claude API klíč (nepovinné – bez něj onboarding použije pravidla; klíč na console.anthropic.com) {nast?.anthropic_api_key_nastaven && <span className="badge good">✓ nastaven {nast.anthropic_api_key_nahled}</span>}
          {nast && !nast.anthropic_sdk && <span className="badge warn">chybí knihovna anthropic – spusťte znovu TenderScope.bat</span>}
        </label>
        <input id="claude" className="field" type="password" value={claudeKey} onChange={(e) => setClaudeKey(e.target.value)} placeholder={nast?.anthropic_api_key_nastaven ? "ponechat stávající" : "sk-ant-…"} />
        {nast?.anthropic_api_key_nastaven && <div className="small muted" style={{ marginTop: 4 }}>Model: {nast.anthropic_model}</div>}
        <div style={{ height: 10 }} />
        <label className="small secondary" htmlFor="vault">Cesta ke složce Obsidian trezoru (vytvoří se v ní podsložka TenderScope)</label>
        <input id="vault" className="field" value={vault} onChange={(e) => setVault(e.target.value)} placeholder="např. C:\Users\Jan\OneDrive\9.semestr\CI\Obsidian\Jan" />
        <label className="small secondary" htmlFor="exa" style={{ marginTop: 10, display: "block" }}>
          Exa API klíč (nepovinné – dohledá k firmě zdroje z webu; klíč na dashboard.exa.ai) {nast?.exa_api_key_nastaven && <span className="badge good">✓ nastaven {nast.exa_api_key_nahled}</span>}
        </label>
        <input id="exa" className="field" type="password" value={exaKey} onChange={(e) => setExaKey(e.target.value)} placeholder={nast?.exa_api_key_nastaven ? "ponechat stávající" : "nevyplněno"} />
        <div className="row" style={{ marginTop: 12 }}>
          <button className="btn primary" onClick={ulozit}>Uložit</button>
          {ulozeno && <span className="badge good">✓ uloženo</span>}
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
