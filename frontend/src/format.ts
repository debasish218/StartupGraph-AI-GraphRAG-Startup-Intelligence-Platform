export function formatMoney(v: number | null | undefined): string {
  if (v === null || v === undefined || Number.isNaN(v)) return '—';
  const abs = Math.abs(v);
  if (abs >= 1e9) return `$${trim(v / 1e9, 1)}B`;
  if (abs >= 1e6) return `$${trim(v / 1e6, 0)}M`;
  if (abs >= 1e3) return `$${trim(v / 1e3, 0)}K`;
  return `$${Math.round(v)}`;
}

function trim(n: number, digits: number): string {
  const s = n.toFixed(digits);
  return s.endsWith('.0') ? s.slice(0, -2) : s;
}

export function formatNumber(v: number | null | undefined): string {
  if (v === null || v === undefined || Number.isNaN(v)) return '—';
  return v.toLocaleString();
}

export function formatPct(v: number | null | undefined, digits = 0): string {
  if (v === null || v === undefined || Number.isNaN(v)) return '—';
  return `${v.toFixed(digits)}%`;
}

/** Format a 0..1 score as a 0..100 number. */
export function formatScore(v: number | null | undefined, digits = 0): string {
  if (v === null || v === undefined || Number.isNaN(v)) return '—';
  return (v * 100).toFixed(digits);
}

export function formatDate(v: string | null | undefined): string {
  if (!v) return '—';
  const d = new Date(v);
  if (Number.isNaN(d.getTime())) return v;
  return d.toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' });
}

export function formatValue(v: unknown, key = ''): string {
  if (v === null || v === undefined) return '—';
  if (Array.isArray(v)) return v.length ? v.map((x) => formatValue(x)).join(', ') : '—';
  if (typeof v === 'object') return JSON.stringify(v);
  if (typeof v === 'number') {
    if (/funding|amount|valuation|volume/i.test(key)) return `${formatMoney(v)} (${v.toLocaleString()})`;
    if (/year/i.test(key)) return String(v);
    return Number.isInteger(v) ? v.toLocaleString() : String(Math.round(v * 1000) / 1000);
  }
  return String(v);
}

export function humanize(s: string): string {
  return s.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase());
}
