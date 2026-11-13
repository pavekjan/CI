import { useEffect, useState } from "react";
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { api, type Trh } from "../api";
import { BarList, Card, ChartTip, Kpi, Loading, go } from "../components";
import { kc, mesic, num, pct } from "../format";

export default function TrhPage({ segment }: { segment: string | null }) {
  const [t, setT] = useState<Trh | null>(null);
  const [vse, setVse] = useState<Trh | null>(null);

  useEffect(() => {
    setT(null);
    api.trh(segment).then(setT);
  }, [segment]);
  useEffect(() => {
    api.trh().then(setVse);
  }, []);

  if (!t) return <Loading />;

  return (
    <div className="grid">
      <div className="row between">
        <h1>{segment ? `Segment ${segment}` : "Celý trh"}</h1>
        <select value={segment ?? ""} onChange={(e) => go(e.target.value ? `/trh/${encodeURIComponent(e.target.value)}` : "/trh")} aria-label="Segment">
          <option value="">Všechny segmenty</option>
          {(vse?.segmenty ?? []).map((s) => (
            <option key={s.segment} value={s.segment}>{s.segment} ({s.pocet})</option>
          ))}
        </select>
      </div>

      <div className="grid g3">
        <Kpi label="Zakázek" value={num(t.zakazek)} note={segment && t.odhadnuto ? `z toho ${num(t.odhadnuto)} s odhadnutým segmentem (podle názvu)` : undefined} />
        <Kpi label="Předpokládaná hodnota celkem" value={kc(t.hodnota)} />
        <Kpi label="Největší dodavatel" value={<span style={{ fontSize: 18 }}>{t.top[0]?.nazev ?? "–"}</span>} note={t.top[0] ? `${pct(t.top[0].podil)} objemu` : undefined} />
      </div>

      <Card title="Vyhlášené zakázky po měsících" sub="Podle data zahájení řízení.">
        <div style={{ height: 240 }}>
          <ResponsiveContainer>
            <BarChart data={t.mesice} margin={{ top: 8, right: 8, left: 0, bottom: 0 }} barCategoryGap="22%">
              <CartesianGrid vertical={false} />
              <XAxis dataKey="mesic" tickFormatter={mesic} tickLine={false} axisLine={false} />
              <YAxis tickLine={false} axisLine={false} width={50} allowDecimals={false} />
              <Tooltip cursor={{ fill: "var(--surface-2)" }} content={({ active, payload }) => (active && payload?.length ? <ChartTip title={mesic(String(payload[0].payload.mesic))} rows={[`${num(payload[0].payload.pocet)} zakázek`]} /> : null)} />
              <Bar dataKey="pocet" fill="var(--series-1)" radius={[4, 4, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </div>
      </Card>

      <div className="grid g2">
        <Card title="Kdo vyhrává" sub="Objem vyhraných zakázek a podíl na trhu (segmentu).">
          <BarList items={t.top} value={(d) => d.objem} label={(d) => d.nazev} right={(d) => <>{kc(d.objem)} · {pct(d.podil)} · {d.vyhry}×</>} onClick={(d) => go(`/firma/${d.ico}`)} />
        </Card>
        <Card title="Regiony" sub="Místo plnění.">
          <BarList items={t.kraje} value={(k) => k.pocet} label={(k) => k.kraj} right={(k) => num(k.pocet)} />
        </Card>
      </div>
    </div>
  );
}
