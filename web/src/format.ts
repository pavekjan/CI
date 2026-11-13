export function kc(x: number | null | undefined, short = true): string {
  if (x === null || x === undefined || isNaN(x)) return "–";
  if (short) {
    if (Math.abs(x) >= 1e9) return `${(x / 1e9).toLocaleString("cs-CZ", { maximumFractionDigits: 2 })} mld. Kč`;
    if (Math.abs(x) >= 1e6) return `${(x / 1e6).toLocaleString("cs-CZ", { maximumFractionDigits: 1 })} mil. Kč`;
    if (Math.abs(x) >= 1e3) return `${(x / 1e3).toLocaleString("cs-CZ", { maximumFractionDigits: 0 })} tis. Kč`;
  }
  return `${Math.round(x).toLocaleString("cs-CZ")} Kč`;
}

export function kcAxis(x: number): string {
  if (Math.abs(x) >= 1e9) return `${(x / 1e9).toLocaleString("cs-CZ", { maximumFractionDigits: 1 })} mld.`;
  if (Math.abs(x) >= 1e6) return `${(x / 1e6).toLocaleString("cs-CZ", { maximumFractionDigits: 0 })} mil.`;
  if (Math.abs(x) >= 1e3) return `${(x / 1e3).toLocaleString("cs-CZ", { maximumFractionDigits: 0 })} tis.`;
  return `${x}`;
}

export function pct(x: number | null | undefined, digits = 0): string {
  if (x === null || x === undefined || isNaN(x)) return "–";
  return `${(x * 100).toLocaleString("cs-CZ", { maximumFractionDigits: digits })} %`;
}

export function num(x: number | null | undefined, digits = 0): string {
  if (x === null || x === undefined || isNaN(x)) return "–";
  return x.toLocaleString("cs-CZ", { maximumFractionDigits: digits });
}

const MES = ["led", "úno", "bře", "dub", "kvě", "čvn", "čvc", "srp", "zář", "říj", "lis", "pro"];
export function mesic(m: string): string {
  const [y, mm] = m.split("-");
  return `${MES[Number(mm) - 1] ?? mm} ${y.slice(2)}`;
}

export function datum(d: string | null | undefined): string {
  if (!d) return "–";
  const [y, m, dd] = d.slice(0, 10).split("-");
  return `${Number(dd)}. ${Number(m)}. ${y}`;
}
