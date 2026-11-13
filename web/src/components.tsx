import { useEffect, useRef, useState, type ReactNode } from "react";
import { api, type Hit } from "./api";
import { kc, num } from "./format";

export function go(path: string) {
  window.location.hash = path;
}

export function Card({ title, sub, children, className = "", right }: { title?: string; sub?: ReactNode; children: ReactNode; className?: string; right?: ReactNode }) {
  return (
    <section className={`card ${className}`}>
      {(title || right) && (
        <div className="row between" style={{ alignItems: "flex-start" }}>
          <div>
            {title && <h2>{title}</h2>}
            {sub && <p className="sub">{sub}</p>}
          </div>
          {right}
        </div>
      )}
      {children}
    </section>
  );
}

export function Kpi({ label, value, note }: { label: string; value: ReactNode; note?: ReactNode }) {
  return (
    <div className="card kpi">
      <div className="label">{label}</div>
      <div className="value">{value}</div>
      {note && <div className="note">{note}</div>}
    </div>
  );
}

export function Loading({ text = "Načítám…" }: { text?: string }) {
  return (
    <div className="empty">
      <span className="spinner" /> {text}
    </div>
  );
}

/** Horizontalni pruhovy seznam: jedna rada = jedna polozka, hodnota vypsana vpravo (bez legendy - jedna rada). */
export function BarList<T>({ items, value, label, right, onClick, max }: {
  items: T[];
  value: (t: T) => number;
  label: (t: T) => ReactNode;
  right: (t: T) => ReactNode;
  onClick?: (t: T) => void;
  max?: number;
}) {
  const m = max ?? Math.max(1, ...items.map(value));
  return (
    <div className="barlist">
      {items.map((t, i) => (
        <div key={i} className={`barrow ${onClick ? "click" : ""}`} onClick={onClick ? () => onClick(t) : undefined} title={typeof label(t) === "string" ? (label(t) as string) : undefined}>
          <div className="name">{label(t)}</div>
          <div className="track">
            <div className="fill" style={{ width: `${Math.max(0.5, (100 * value(t)) / m)}%` }} />
          </div>
          <div className="val">{right(t)}</div>
        </div>
      ))}
    </div>
  );
}

export function SearchBox({ compact = false, autoFocus = false }: { compact?: boolean; autoFocus?: boolean }) {
  const [q, setQ] = useState("");
  const [hits, setHits] = useState<Hit[]>([]);
  const [open, setOpen] = useState(false);
  const [sel, setSel] = useState(0);
  const [busy, setBusy] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (q.trim().length < 2) {
      setHits([]);
      return;
    }
    setBusy(true);
    const t = setTimeout(() => {
      api.hledat(q).then((h) => { setHits(h); setSel(0); setOpen(true); }).catch(() => setHits([])).finally(() => setBusy(false));
    }, 220);
    return () => clearTimeout(t);
  }, [q]);

  useEffect(() => {
    const close = (e: MouseEvent) => { if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false); };
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, []);

  const pick = (h: Hit) => { setOpen(false); setQ(""); go(`/firma/${h.ico}`); };

  return (
    <div className={`search ${compact ? "compact" : ""}`} ref={ref}>
      <svg className="icon" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round"><circle cx="11" cy="11" r="7" /><path d="m20 20-4-4" /></svg>
      <input
        value={q}
        autoFocus={autoFocus}
        placeholder={compact ? "Hledat firmu nebo IČO…" : "Zadejte název firmy nebo IČO, např. 27082440"}
        onChange={(e) => setQ(e.target.value)}
        onFocus={() => hits.length && setOpen(true)}
        onKeyDown={(e) => {
          if (e.key === "ArrowDown") { setSel((s) => Math.min(s + 1, hits.length - 1)); e.preventDefault(); }
          if (e.key === "ArrowUp") { setSel((s) => Math.max(s - 1, 0)); e.preventDefault(); }
          if (e.key === "Enter") {
            if (hits[sel]) pick(hits[sel]);
            else if (/^\d{6,8}$/.test(q.trim())) go(`/firma/${q.trim().padStart(8, "0")}`);
          }
          if (e.key === "Escape") setOpen(false);
        }}
      />
      {open && q.trim().length >= 2 && (
        <div className="results">
          {busy && hits.length === 0 && <div className="result muted">Hledám…</div>}
          {!busy && hits.length === 0 && <div className="result muted">Nic nenalezeno. Zkuste IČO nebo jinou část názvu.</div>}
          {hits.map((h, i) => (
            <a key={h.ico} className={`result ${i === sel ? "sel" : ""}`} onMouseEnter={() => setSel(i)} onClick={() => pick(h)}>
              <span>
                {h.nazev || "(bez názvu)"} <span className="muted small">IČO {h.ico}</span>
              </span>
              <span className="meta">
                {h.jen_ares ? "jen v ARES, bez zakázek" : `${num(h.vyhry)} výher v soutěžích · ${kc(h.objem)}${h.smluv_rs ? ` · ${num(h.smluv_rs)} smluv` : ""}`}
              </span>
            </a>
          ))}
        </div>
      )}
    </div>
  );
}

export function ChartTip({ title, rows }: { title: ReactNode; rows: ReactNode[] }) {
  return (
    <div className="tt">
      <b>{title}</b>
      {rows.map((r, i) => <div key={i}>{r}</div>)}
    </div>
  );
}
