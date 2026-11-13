import { useEffect, useMemo, useState } from "react";
import {
  Bar, BarChart, CartesianGrid, ReferenceLine, ResponsiveContainer, Scatter, ScatterChart, Tooltip, XAxis, YAxis, ZAxis,
} from "recharts";
import { api, type ExportVysledek, type Profil } from "../api";
import { BarList, Card, ChartTip, Kpi, Loading, go } from "../components";
import { datum, kc, kcAxis, mesic, num, pct } from "../format";
import GrafCard from "./Graf";

type Metrika = "vyhry" | "objem" | "ucasti";

function ScoreBadge({ h }: { h: string | null }) {
  if (!h) return <span className="badge neutral">nelze určit</span>;
  const cls = h === "vysoká" ? "good" : h === "střední" ? "warn" : "bad";
  const icon = h === "vysoká" ? "▲" : h === "střední" ? "■" : "▼";
  return <span className={`badge ${cls}`}>{icon} {h} konkurenceschopnost</span>;
}

export default function Firma({ ico, prazdnaDb }: { ico: string; prazdnaDb?: boolean }) {
  const [p, setP] = useState<Profil | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [metrika, setMetrika] = useState<Metrika>("vyhry");
  const [filtr, setFiltr] = useState<"vse" | "výhra" | "neúspěch">("vse");
  const [limit, setLimit] = useState(25);
  const [exp, setExp] = useState<ExportVysledek | null>(null);
  const [expBusy, setExpBusy] = useState(false);
  const [expErr, setExpErr] = useState<string | null>(null);
  const doExport = async () => {
    setExpBusy(true);
    setExpErr(null);
    try {
      setExp(await api.export(ico));
    } catch (e) {
      setExpErr(String((e as Error).message || e));
    } finally {
      setExpBusy(false);
    }
  };

  useEffect(() => {
    setP(null);
    setErr(null);
    setLimit(25);
    setExp(null);
    api.firma(ico).then(setP).catch((e) => setErr(String(e.message || e)));
    window.scrollTo(0, 0);
  }, [ico]);

  const zak = useMemo(() => (p ? p.zakazky.filter((z) => filtr === "vse" || z.vysledek === filtr) : []), [p, filtr]);

  if (err) return <div className="card empty">Chyba: {err}</div>;
  if (!p) return <Loading text="Počítám profil firmy…" />;

  const k = p.kpi;
  const bezDat = k.vyhry === 0 && k.ucasti === 0;
  const maxH2h = Math.max(1, ...p.souboje.map((s) => Math.max(s.my_vyhra, s.oni_vyhra)));
  const metLabel: Record<Metrika, string> = { vyhry: "Výhry", objem: "Objem výher", ucasti: "Účasti" };

  return (
    <div className="grid">
      {/* hlavicka */}
      <div className="card">
        <div className="row between">
          <div>
            <div className="row" style={{ gap: 10 }}>
              <h1>{p.nazev}</h1>
              {!bezDat && <ScoreBadge h={p.skore.hodnoceni} />}
              {p.ares?.datum_zaniku && <span className="badge bad">✕ zaniklá {datum(p.ares.datum_zaniku)}</span>}
            </div>
            <div className="secondary" style={{ marginTop: 4 }}>
              IČO {p.ico}
              {p.ares?.sidlo && <> · {p.ares.sidlo}</>}
              {p.ares?.datum_vzniku && <> · vznik {datum(p.ares.datum_vzniku)}</>}
              {p.ares?.nace && <> · NACE {p.ares.nace.split(",").slice(0, 4).join(", ")}</>}
            </div>
          </div>
          <div className="row small">
            <a href={`https://ares.gov.cz/ekonomicke-subjekty?ico=${p.ico}`} target="_blank" rel="noreferrer">ARES ↗</a>
            <a href={`https://www.hlidacstatu.cz/subjekt/${p.ico}`} target="_blank" rel="noreferrer">Hlídač státu ↗</a>
            <a className="btn" href={`#/onboarding/${p.ico}`} title="4 otázky, profil firmy a zakázky, které by ji zajímaly">Onboarding a zpravodaj</a>
            {!bezDat && (
              <button className="btn primary" onClick={doExport} disabled={expBusy} title="Vytvoří propojené poznámky (knowledge graph) pro Obsidian">
                {expBusy ? <><span className="spinner" /> Exportuji…</> : "Export do Obsidianu"}
              </button>
            )}
          </div>
        </div>
        {expErr && <div className="callout" style={{ marginTop: 12 }}>Export selhal: {expErr}</div>}
        {exp && (
          <div className="callout info" style={{ marginTop: 12 }}>
            ✓ Vytvořeno <b>{exp.poznamek}</b> propojených poznámek a <b>{exp.zdroju}</b> zdrojových záznamů{exp.exa ? ` (z toho ${exp.exa} z Exa)` : ""}.{" "}
            {exp.zapsano ? <>Zapsáno do trezoru: <code>{exp.zapsano}</code>. V Obsidianu otevřete <b>00_Prehled</b> a graf (Ctrl+G).</> : exp.chyba_zapisu ? <>{exp.chyba_zapisu}. </> : <>Cestu k trezoru můžete nastavit na stránce <a href="#/data">Data</a>, pak se export zapíše rovnou. </>}{" "}
            <a href={exp.zip}>Stáhnout jako ZIP</a>
          </div>
        )}
      </div>

      {bezDat ? (
        prazdnaDb ? (
        <div className="card empty">
          <p><b>Databáze zakázek je zatím prázdná – nejdřív je potřeba stáhnout data.</b></p>
          <p>Na záložce <a href="#/data">Data</a> je popsané, jak data stáhnout (na vlastním počítači tlačítkem <b>Rychlá aktualizace</b>).</p>
          <p><a className="btn primary" href="#/data">Přejít na Data</a></p>
        </div>
        ) : (
        <div className="card empty">
          <p><b>V načtených datech nemá tato firma žádnou zakázku.</b></p>
          <p>Buď se veřejných zakázek neúčastní, nebo v období, které máte stažené, nesoutěžila. Zkuste na stránce <a href="#/data">Data</a> stáhnout delší období.</p>
        </div>
        )
      ) : (
        <>
          {/* skore */}
          <Card title="Skóre konkurenceschopnosti" sub="Vážený průměr pěti složek (0–100) ze soutěží (RVZ) i Registru smluv. Každá složka ukazuje, z čeho vychází."
            right={p.skore.malo_dat ? <span className="badge warn" title="Málo soutěží nebo složek – skóre je jen orientační">málo dat</span> : undefined}>
            <div className="grid scoregrid">
              <div className="score">
                <div className="score-num">{p.skore.celkem ?? "–"}<small> / 100</small></div>
              </div>
              <div>
                {p.skore.slozky.map((s) => (
                  <div className="comp" key={s.klic}>
                    <div><b>{s.nazev}</b> <span className="muted small">váha {s.vaha} %</span>{s.malo_dat && <span className="badge warn" style={{ marginLeft: 6 }}>málo dat</span>}</div>
                    <div className="meter" role="meter" aria-valuenow={s.skore ?? 0} aria-valuemin={0} aria-valuemax={100} aria-label={s.nazev}>
                      <div style={{ width: `${s.skore ?? 0}%`, opacity: s.skore === null ? 0 : 1 }} />
                    </div>
                    <div className="num" style={{ textAlign: "right", fontWeight: 700 }}>{s.skore ?? "–"}</div>
                    <div className="why">{s.vysvetleni}</div>
                  </div>
                ))}
              </div>
            </div>
          </Card>

          {/* odkud data jsou */}
          <div className="callout info small">
            <b>Proč jsou čísla jiná než na Hlídači státu?</b>{" "}
            <b>Soutěže (RVZ)</b>{p.obdobi?.rvz_od ? <> za {mesic(p.obdobi.rvz_od)} – {mesic(p.obdobi.rvz_do!)}</> : null}: zakázky z věstníku
            a NEN se známými účastníky. <b>Registr smluv</b>{p.obdobi?.rs_od ? <> za {mesic(p.obdobi.rs_od)} – {mesic(p.obdobi.rs_do!)}</> : null}: zveřejněné
            smlouvy nad 50 tis. Kč, tedy i malé zakázky a objednávky. Hlídač státu ukazuje <b>celou historii od roku 2016</b> a navíc
            zakázky malého rozsahu z profilů zadavatelů, proto má vyšší čísla.
            {p.hlidac && <>
              {" "}<a href={p.hlidac.url} target="_blank" rel="noreferrer">
                {p.hlidac.pocet != null ? <>Hlídač: {num(p.hlidac.pocet)} smluv ↗</> : <>Smlouvy na Hlídači ↗</>}
              </a>
              {p.hlidac.zakazky_url && <>{" · "}<a href={p.hlidac.zakazky_url} target="_blank" rel="noreferrer">
                {p.hlidac.zakazky != null ? <>Hlídač: {num(p.hlidac.zakazky)} zakázek jako dodavatel ↗</> : <>Zakázky na Hlídači ↗</>}
              </a></>}
            </>}
          </div>

          {/* KPI */}
          <div className="grid g4">
            <Kpi label="Vyhrané soutěže (RVZ)" value={num(k.vyhry)} note={`${num(k.ucasti)} účastí celkem`} />
            <Kpi label="Win rate" value={pct(k.win_rate)} note={k.win_rate === null ? "zdroj neuvádí neúspěšné nabídky" : `ze ${num(k.ucasti_zname)} soutěží se známými účastníky`} />
            <Kpi label="Objem výher (bez DPH)" value={kc(k.objem)} note={`medián zakázky ${kc(k.median_cena)}`} />
            <Kpi label="Cena vs. předpokládaná hodnota" value={pct(k.median_pomer)} note={`trh ve stejných segmentech ${pct(k.trh_median_pomer)}`} />
          </div>
          <div className="grid g4">
            <Kpi label="Zákazníků (zadavatelů)" value={num(k.klientu)} />
            <Kpi label="Ø nabídek v soutěžích, které vyhrála" value={num(k.prumer_nabidek, 1)} note={k.s_poctem_nabidek ? `${k.jedna_nabidka}× byla jediným uchazečem` : undefined} />
            <Kpi label="Smlouvy v Registru smluv" value={num(Math.max(k.smluv_rs_souhrn ?? 0, k.smluv_rs))}
              note={`${kc(Math.max(k.objem_rs_souhrn ?? 0, k.objem_rs))}${p.registr ? ` · ${num(p.registr.zadavatelu)} odběratelů` : ""}`} />
            <Kpi label="Výhry ověřené v Registru smluv" value={k.vyhry ? pct(k.overeno_rs / k.vyhry) : "–"} note={`${k.overeno_rs} z ${k.vyhry} (křížová kontrola)`} />
          </div>

          {p.registr && p.registr.pocet > 0 && (
            <div className="grid g2">
              <Card title="Smlouvy z Registru smluv po měsících" sub="Počet zveřejněných smluv podle data uzavření (včetně malých zakázek mimo RVZ).">
                <div style={{ height: 220 }}>
                  <ResponsiveContainer>
                    <BarChart data={p.registr.mesice} margin={{ top: 8, right: 8, left: 0, bottom: 0 }} barCategoryGap="22%">
                      <CartesianGrid vertical={false} strokeDasharray="0" />
                      <XAxis dataKey="mesic" tickFormatter={mesic} tickLine={false} axisLine={false} />
                      <YAxis tickLine={false} axisLine={false} width={50} allowDecimals={false} />
                      <Tooltip cursor={{ fill: "var(--surface-2)" }} content={({ active, payload }) => (active && payload?.length
                        ? <ChartTip title={mesic(String(payload[0].payload.mesic))} rows={[`${num(payload[0].payload.pocet)} smluv`, kc(payload[0].payload.objem)]} /> : null)} />
                      <Bar dataKey="pocet" fill="var(--series-2, var(--series-1))" radius={[4, 4, 0, 0]} />
                    </BarChart>
                  </ResponsiveContainer>
                </div>
              </Card>
              <Card title="Odběratelé podle Registru smluv" sub="Veřejní zadavatelé podle objemu smluv (bez DPH).">
                <BarList items={p.registr.odberatele} value={(c) => c.objem} label={(c) => c.nazev} right={(c) => <>{kc(c.objem)} · {num(c.pocet)}×</>} />
              </Card>
            </div>
          )}

          <GrafCard ico={p.ico} />

          {/* vyvoj */}
          <Card
            title={`${metLabel[metrika]} po měsících`}
            sub="Podle data zahájení zadávacího řízení."
            right={
              <div className="seg" role="tablist">
                {(["vyhry", "objem", "ucasti"] as Metrika[]).map((m) => (
                  <button key={m} className={metrika === m ? "on" : ""} onClick={() => setMetrika(m)}>{metLabel[m]}</button>
                ))}
              </div>
            }
          >
            <div style={{ height: 260 }}>
              <ResponsiveContainer>
                <BarChart data={p.mesice} margin={{ top: 8, right: 8, left: 0, bottom: 0 }} barCategoryGap="22%">
                  <CartesianGrid vertical={false} strokeDasharray="0" />
                  <XAxis dataKey="mesic" tickFormatter={mesic} tickLine={false} axisLine={false} />
                  <YAxis tickFormatter={metrika === "objem" ? kcAxis : (v) => num(v)} tickLine={false} axisLine={false} width={60} allowDecimals={false} />
                  <Tooltip
                    cursor={{ fill: "var(--surface-2)" }}
                    content={({ active, payload }) =>
                      active && payload?.length ? (
                        <ChartTip
                          title={mesic(String(payload[0].payload.mesic))}
                          rows={[`Výhry: ${num(payload[0].payload.vyhry)}`, `Objem: ${kc(payload[0].payload.objem)}`, `Účasti: ${num(payload[0].payload.ucasti)}`]}
                        />
                      ) : null
                    }
                  />
                  <Bar dataKey={metrika} fill="var(--series-1)" radius={[4, 4, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          </Card>

          <div className="grid g2">
            <Card title="Segmenty (oddíly CPV)" sub="Objem výher; vpravo podíl na objemu segmentu a pořadí mezi dodavateli.">
              <BarList
                items={p.segmenty}
                value={(s) => s.objem}
                label={(s) => s.segment}
                right={(s) => <>{kc(s.objem)} · <b>{pct(s.podil)}</b> · {s.poradi ?? "–"}./{s.dodavatelu}</>}
              />
            </Card>
            <Card title="Největší zákazníci" sub="Zadavatelé podle objemu vyhraných zakázek.">
              <BarList items={p.klienti} value={(c) => c.objem} label={(c) => c.nazev} right={(c) => <>{kc(c.objem)} · {c.vyhry}×</>} />
            </Card>
          </div>

          {/* ceny */}
          <Card
            title="Vítězná cena vs. předpokládaná hodnota"
            sub={<>Každý bod je jedna vyhraná zakázka. Body pod čárou = nabídla méně, než zadavatel čekal. Medián {pct(k.median_pomer)}, trh {pct(k.trh_median_pomer)}.</>}
          >
            {p.ceny.length < 2 ? (
              <div className="empty">Málo zakázek s oběma údaji.</div>
            ) : (
              <div style={{ height: 320 }}>
                <ResponsiveContainer>
                  <ScatterChart margin={{ top: 8, right: 16, left: 0, bottom: 8 }}>
                    <CartesianGrid strokeDasharray="0" />
                    <XAxis type="number" dataKey="odhad" name="Předpokládaná hodnota" scale="log" domain={["auto", "auto"]} tickFormatter={kcAxis} tickLine={false} axisLine={false}
                      label={{ value: "předpokládaná hodnota", position: "insideBottomRight", offset: -4, className: "recharts-text" }} />
                    <YAxis type="number" dataKey="cena" name="Cena" scale="log" domain={["auto", "auto"]} tickFormatter={kcAxis} tickLine={false} axisLine={false} width={64} />
                    <ZAxis range={[70, 70]} />
                    <ReferenceLine
                      segment={[
                        { x: Math.min(...p.ceny.map((c) => Math.min(c.odhad, c.cena))), y: Math.min(...p.ceny.map((c) => Math.min(c.odhad, c.cena))) },
                        { x: Math.max(...p.ceny.map((c) => Math.max(c.odhad, c.cena))), y: Math.max(...p.ceny.map((c) => Math.max(c.odhad, c.cena))) },
                      ]}
                      stroke="var(--text-muted)" strokeDasharray="4 4" ifOverflow="extendDomain"
                    />
                    <Tooltip
                      cursor={false}
                      content={({ active, payload }) =>
                        active && payload?.length ? (
                          <ChartTip title={payload[0].payload.nazev} rows={[`Odhad: ${kc(payload[0].payload.odhad)}`, `Cena: ${kc(payload[0].payload.cena)}`, `Poměr: ${pct(payload[0].payload.pomer)}`, payload[0].payload.segment]} />
                        ) : null
                      }
                    />
                    <Scatter data={p.ceny} fill="var(--series-1)" stroke="var(--surface-1)" strokeWidth={2} />
                  </ScatterChart>
                </ResponsiveContainer>
              </div>
            )}
          </Card>

          <div className="grid g2">
            <Card title="Přímé souboje" sub="Soutěže, kde se firma potkala s konkurentem (podle seznamu účastníků).">
              {p.souboje.length === 0 ? (
                <div className="empty">Zdroj u těchto zakázek neuvádí ostatní účastníky.</div>
              ) : (
                <>
                  <div className="legend">
                    <span><i style={{ background: "var(--series-1)" }} />vyhrál(a) {p.nazev.split(" ")[0]}</span>
                    <span><i style={{ background: "var(--series-2)" }} />vyhrál konkurent</span>
                  </div>
                  {p.souboje.slice(0, 10).map((s) => (
                    <div className="h2h" key={s.ico} title={`${s.stretu} společných soutěží`}>
                      <a className="name" style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }} onClick={() => go(`/firma/${s.ico}`)}>{s.nazev}</a>
                      <span className="muted small num">{s.stretu}× spolu</span>
                      <div className="l"><div className="fill" style={{ width: `${(100 * s.my_vyhra) / maxH2h}%` }} /></div>
                      <div className="r row" style={{ gap: 6 }}><div className="fill" style={{ width: `${(80 * s.oni_vyhra) / maxH2h}%` }} /><span className="small secondary">{s.my_vyhra}:{s.oni_vyhra}</span></div>
                    </div>
                  ))}
                </>
              )}
            </Card>
            <Card title="Hlavní rivalové v segmentech" sub="Kdo vyhrává nejvíc ve stejných oddílech CPV (i bez přímého střetu).">
              <BarList items={p.rivalove} value={(r) => r.objem} label={(r) => r.nazev} right={(r) => <>{kc(r.objem)} · {r.vyhry}×</>} onClick={(r) => go(`/firma/${r.ico}`)} />
            </Card>
          </div>

          <div className="grid g2">
            <Card title="Kde by mohla soutěžit teď" sub="Otevřené zakázky v jejích hlavních segmentech (lhůta ještě běží).">
              {p.prilezitosti.length === 0 ? (
                <div className="empty">V datech teď nejsou otevřené zakázky v jejích segmentech.</div>
              ) : (
                p.prilezitosti.slice(0, 8).map((o) => (
                  <div className="opp" key={o.id}>
                    <div className="row between">
                      {o.url ? <a href={o.url} target="_blank" rel="noreferrer"><b>{o.nazev}</b></a> : <b>{o.nazev}</b>}
                      {o.klient && <span className="badge good">● stávající klient</span>}
                    </div>
                    <div className="small secondary">{o.zadavatel} · {kc(o.hodnota)} · lhůta {datum(o.lhuta)}</div>
                  </div>
                ))
              )}
            </Card>
            <Card title="Regiony" sub="Místo plnění vyhraných zakázek.">
              <BarList items={p.regiony} value={(r) => r.pocet} label={(r) => r.kraj} right={(r) => `${r.pocet}×`} />
            </Card>
          </div>

          <Card
            title="Zakázky"
            sub="Klikněte na název pro detail na NEN / Věstníku."
            right={
              <div className="seg">
                {(["vse", "výhra", "neúspěch"] as const).map((f) => (
                  <button key={f} className={filtr === f ? "on" : ""} onClick={() => { setFiltr(f); setLimit(25); }}>{f === "vse" ? "Vše" : f === "výhra" ? "Výhry" : "Neúspěchy"}</button>
                ))}
              </div>
            }
          >
            <div className="table-wrap">
              <table>
                <thead>
                  <tr><th>Datum</th><th>Zakázka</th><th>Zadavatel</th><th className="num">Odhad</th><th className="num">Cena</th><th className="num">Nabídek</th><th>Výsledek</th></tr>
                </thead>
                <tbody>
                  {zak.slice(0, limit).map((z) => (
                    <tr key={z.id}>
                      <td className="num">{datum(z.datum)}</td>
                      <td>{z.url ? <a href={z.url} target="_blank" rel="noreferrer">{z.nazev}</a> : z.nazev}<div className="muted small">{z.segment}</div></td>
                      <td>{z.zadavatel}</td>
                      <td className="num">{kc(z.odhad)}</td>
                      <td className="num">{kc(z.cena)}</td>
                      <td className="num">{z.nabidek ?? "–"}</td>
                      <td>
                        <span className={`badge ${z.vysledek === "výhra" ? "good" : "neutral"}`}>{z.vysledek === "výhra" ? "✓ výhra" : "✕ neúspěch"}</span>
                        {z.overeno_rs && <span className="muted small" title="Smlouva nalezena v Registru smluv"> · RS ✓</span>}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {zak.length > limit && (
              <div className="row" style={{ marginTop: 12 }}>
                <button className="btn" onClick={() => setLimit((l) => l + 50)}>Zobrazit další</button>
                <span className="muted small">zobrazeno {limit} z {zak.length}</span>
              </div>
            )}
          </Card>

          {(p.priznaky.length > 0 || p.zpravy.length > 0) && (
            <div className="grid g2">
              {p.priznaky.length > 0 && (
                <Card title="Upozornění z kontroly dat">
                  {p.priznaky.map((f, i) => <div className="callout" key={i} style={{ marginBottom: 8 }}>⚠ {f.popis}</div>)}
                </Card>
              )}
              {p.zpravy.length > 0 && (
                <Card title="Zprávy" sub="Google News">
                  {p.zpravy.map((z) => (
                    <div className="opp" key={z.url}><a href={z.url} target="_blank" rel="noreferrer">{z.titulek}</a><div className="small muted">{datum(z.datum)} · {z.zdroj}</div></div>
                  ))}
                </Card>
              )}
            </div>
          )}
        </>
      )}
    </div>
  );
}
