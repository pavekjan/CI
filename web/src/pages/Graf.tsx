import { useEffect, useMemo, useRef, useState } from "react";
import { api, type Graf, type GrafUzel } from "../api";
import { Card, Loading, go } from "../components";

// Knowledge graph firmy: jednoducha silova simulace (bez dalsich knihoven), uzly jdou presouvat mysi.
const BARVA: Record<GrafUzel["typ"], string> = {
  firma: "var(--series-1)", obor: "#8a5cf6", zadavatel: "#16a34a", konkurent: "var(--series-2)", zakazka: "#64748b", zdroj: "#0ea5e9",
};
const POPIS: Record<GrafUzel["typ"], string> = {
  firma: "Firma", obor: "Obor (CPV)", zadavatel: "Zákazník (zadavatel)", konkurent: "Konkurent", zakazka: "Vyhraná zakázka", zdroj: "Zdroj dat",
};
const W = 900, H = 620;

type Poz = Record<string, { x: number; y: number }>;

function rozlozeni(g: Graf): Poz {
  const n = g.uzly.length;
  const p: Poz = {};
  const typy = Object.keys(BARVA);
  g.uzly.forEach((u, i) => {
    if (u.typ === "firma" && i === 0) { p[u.id] = { x: W / 2, y: H / 2 }; return; }
    const a = (i / n) * Math.PI * 2 + typy.indexOf(u.typ);
    const r = u.typ === "zakazka" || u.typ === "zdroj" ? 260 : 170;
    p[u.id] = { x: W / 2 + Math.cos(a) * r, y: H / 2 + Math.sin(a) * r };
  });
  const v: Record<string, { x: number; y: number }> = {};
  g.uzly.forEach((u) => (v[u.id] = { x: 0, y: 0 }));
  for (let it = 0; it < 300; it++) {
    const t = 1 - it / 300;
    for (let i = 0; i < n; i++) for (let j = i + 1; j < n; j++) {
      const a = p[g.uzly[i].id], b = p[g.uzly[j].id];
      let dx = a.x - b.x, dy = a.y - b.y;
      const d2 = Math.max(dx * dx + dy * dy, 25);
      const f = 7000 / d2;
      const d = Math.sqrt(d2); dx /= d; dy /= d;
      v[g.uzly[i].id].x += dx * f; v[g.uzly[i].id].y += dy * f;
      v[g.uzly[j].id].x -= dx * f; v[g.uzly[j].id].y -= dy * f;
    }
    for (const h of g.hrany) {
      const a = p[h.od], b = p[h.do];
      if (!a || !b) continue;
      const dx = b.x - a.x, dy = b.y - a.y, d = Math.sqrt(dx * dx + dy * dy) || 1;
      const f = (d - 150) * 0.02;
      v[h.od].x += (dx / d) * f; v[h.od].y += (dy / d) * f;
      v[h.do].x -= (dx / d) * f; v[h.do].y -= (dy / d) * f;
    }
    g.uzly.forEach((u, i) => {
      if (i === 0) { p[u.id] = { x: W / 2, y: H / 2 }; v[u.id] = { x: 0, y: 0 }; return; }
      p[u.id].x = Math.min(W - 40, Math.max(40, p[u.id].x + v[u.id].x * t));
      p[u.id].y = Math.min(H - 25, Math.max(25, p[u.id].y + v[u.id].y * t));
      v[u.id].x *= 0.5; v[u.id].y *= 0.5;
    });
  }
  return p;
}

function otevri(u: GrafUzel) {
  if (!u.odkaz) return;
  if (u.odkaz.startsWith("#/")) go(u.odkaz.slice(1));
  else window.open(u.odkaz, "_blank", "noopener,noreferrer");
}

export default function GrafCard({ ico }: { ico: string }) {
  const [g, setG] = useState<Graf | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [hover, setHover] = useState<string | null>(null);
  const [poz, setPoz] = useState<Poz>({});
  const [tah, setTah] = useState<string | null>(null);
  const posun = useRef(false);

  useEffect(() => {
    setG(null); setErr(null);
    api.graf(ico).then((d) => { setG(d); setPoz(rozlozeni(d)); }).catch((e) => setErr(String(e.message ?? e)));
  }, [ico]);

  const sousede = useMemo(() => {
    const s = new Set<string>();
    if (g && hover) { s.add(hover); g.hrany.forEach((h) => { if (h.od === hover) s.add(h.do); if (h.do === hover) s.add(h.od); }); }
    return s;
  }, [g, hover]);

  if (err) return <Card title="Knowledge graph"><div className="callout">{err}</div></Card>;
  if (!g) return <Card title="Knowledge graph"><Loading text="Skládám graf…" /></Card>;

  const svgBod = (e: React.PointerEvent<SVGSVGElement>) => {
    const r = e.currentTarget.getBoundingClientRect();
    return { x: ((e.clientX - r.left) / r.width) * W, y: ((e.clientY - r.top) / r.height) * H };
  };
  const typy = Array.from(new Set(g.uzly.map((u) => u.typ)));

  return (
    <Card title="Knowledge graph" sub="Firma, její zákazníci, konkurenti, obory, vyhrané zakázky a zdroje dat. Kliknutím uzel otevřete, tažením ho posunete.">
      <div className="row" style={{ gap: 14, flexWrap: "wrap", marginBottom: 8 }}>
        {typy.map((t) => (
          <span key={t} className="small secondary" style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
            <span style={{ width: 10, height: 10, borderRadius: 99, background: BARVA[t] }} />{POPIS[t]}
          </span>
        ))}
      </div>
      <svg viewBox={`0 0 ${W} ${H}`} style={{ width: "100%", height: "auto", touchAction: "none", userSelect: "none" }}
        role="img" aria-label={`Knowledge graph firmy ${g.nazev}`}
        onPointerMove={(e) => { if (tah) { posun.current = true; const b = svgBod(e); setPoz((p) => ({ ...p, [tah]: b })); } }}
        onPointerUp={() => setTah(null)} onPointerLeave={() => setTah(null)}>
        {g.hrany.map((h, i) => {
          const a = poz[h.od], b = poz[h.do];
          if (!a || !b) return null;
          const svit = !hover || (sousede.has(h.od) && sousede.has(h.do));
          return <line key={i} x1={a.x} y1={a.y} x2={b.x} y2={b.y} stroke="var(--border-strong, #94a3b8)"
            strokeDasharray={h.typ === "konkurent" || h.typ === "souboj" ? "5 4" : undefined}
            strokeOpacity={svit ? 0.7 : 0.12} strokeWidth={h.typ === "zdroj" ? 1 : 1.5} />;
        })}
        {g.uzly.map((u) => {
          const b = poz[u.id];
          if (!b) return null;
          const r = 6 + u.vaha * 4;
          const svit = !hover || sousede.has(u.id);
          return (
            <g key={u.id} transform={`translate(${b.x},${b.y})`} style={{ cursor: u.odkaz ? "pointer" : "default", opacity: svit ? 1 : 0.25 }}
              onPointerEnter={() => setHover(u.id)} onPointerLeave={() => setHover(null)}
              onPointerDown={(e) => { e.preventDefault(); posun.current = false; setTah(u.id); }}
              onClick={() => { if (!posun.current) otevri(u); }}>
              <title>{`${POPIS[u.typ]}: ${u.nazev}${u.info ? ` (${u.info})` : ""}${u.odkaz ? " – kliknutím otevřete" : ""}`}</title>
              <circle r={r} fill={BARVA[u.typ]} stroke="var(--surface, #fff)" strokeWidth={2} />
              <text y={r + 13} textAnchor="middle" fontSize={u.typ === "firma" ? 14 : 11} fontWeight={u.typ === "firma" ? 700 : 400}
                fill="var(--text, #111)" stroke="var(--surface, #fff)" strokeWidth={3} paintOrder="stroke" strokeLinejoin="round">{u.nazev.length > 28 ? u.nazev.slice(0, 27) + "…" : u.nazev}</text>
            </g>
          );
        })}
      </svg>
    </Card>
  );
}
