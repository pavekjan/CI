import { useEffect, useState } from "react";
import { api, type Stav, type Trh } from "../api";
import { BarList, Card, Kpi, SearchBox, go } from "../components";
import { datum, kc, num, pct } from "../format";

export default function Home({ stav }: { stav: Stav | null }) {
  const [trh, setTrh] = useState<Trh | null>(null);
  useEffect(() => {
    api.trh().then(setTrh).catch(() => setTrh(null));
  }, [stav?.zakazek]);

  const prazdno = stav && stav.zakazek === 0;

  return (
    <div className="grid">
      <div className="hero">
        <h1>Jak konkurenceschopná je firma ve veřejných zakázkách?</h1>
        <p>Zadejte libovolnou firmu. TenderScope z otevřených dat státu spočítá, kolik vyhrává, za jaké ceny, u koho, proti komu a jak si stojí v segmentu.</p>
        <SearchBox autoFocus />
      </div>

      {prazdno && (
        <div className="callout info">
          Databáze je zatím prázdná. Otevřete stránku <a href="#/data">Data</a> a klikněte na <b>Rychlá aktualizace</b>: stáhnou se zakázky za poslední 3 měsíce (pár minut).
        </div>
      )}

      {stav && !prazdno && (
        <div className="grid g4">
          <Kpi label="Zakázek v databázi" value={num(stav.zakazek)} note={stav.od ? `${datum(stav.od)} – ${datum(stav.do)}` : undefined} />
          <Kpi label="Dodavatelů" value={num(stav.dodavatelu)} />
          <Kpi label="Vítězných nabídek" value={num(stav.vitezu)} />
          <Kpi label="Smluv z Registru smluv" value={num(stav.smluv)} />
        </div>
      )}

      {trh && trh.top.length > 0 && (
        <div className="grid g2">
          <Card title="Největší dodavatelé" sub="Podle objemu vyhraných zakázek (bez DPH). Kliknutím otevřete profil.">
            <BarList
              items={trh.top.slice(0, 12)}
              value={(t) => t.objem}
              label={(t) => t.nazev}
              right={(t) => <>{kc(t.objem)} · {pct(t.podil)}</>}
              onClick={(t) => go(`/firma/${t.ico}`)}
            />
          </Card>
          <Card title="Segmenty trhu" sub="Počet zakázek podle oddílu CPV. Kliknutím zobrazíte detail segmentu.">
            <BarList
              items={trh.segmenty.slice(0, 12)}
              value={(s) => s.pocet}
              label={(s) => s.segment}
              right={(s) => num(s.pocet)}
              onClick={(s) => go(`/trh/${encodeURIComponent(s.segment)}`)}
            />
          </Card>
        </div>
      )}
    </div>
  );
}
