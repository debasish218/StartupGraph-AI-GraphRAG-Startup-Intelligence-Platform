import { useMemo } from 'react';
import { Bar, BarChart, CartesianGrid, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import type { SectorRow, TrendRow } from '../api';
import { formatMoney, formatPct } from '../format';
import { useChartTheme } from '../theme';

const MAX_SERIES = 7; // + "Other" = 8 categorical slots

export function FundingTrendsChart({ rows }: { rows: TrendRow[] }) {
  const theme = useChartTheme();
  const { data, sectors } = useMemo(() => {
    const totals = new Map<string, number>();
    for (const r of rows) {
      const s = r.sector ?? 'Unknown';
      totals.set(s, (totals.get(s) ?? 0) + (r.amount ?? 0));
    }
    const ranked = [...totals.entries()].sort((a, b) => b[1] - a[1]).map(([s]) => s);
    const top = ranked.slice(0, ranked.length > MAX_SERIES + 1 ? MAX_SERIES : MAX_SERIES + 1);
    const hasOther = ranked.length > top.length;
    const topSet = new Set(top);
    const byYear = new Map<number, Record<string, number>>();
    for (const r of rows) {
      if (r.year === null || r.year === undefined) continue;
      const key = topSet.has(r.sector ?? 'Unknown') ? (r.sector ?? 'Unknown') : 'Other';
      const rec = byYear.get(r.year) ?? { year: r.year };
      rec[key] = (rec[key] ?? 0) + (r.amount ?? 0);
      byYear.set(r.year, rec);
    }
    // Sort sectors alphabetically so colour follows the sector, not its rank.
    const sectorsSorted = [...top].sort();
    return {
      data: [...byYear.values()].sort((a, b) => a.year - b.year),
      sectors: hasOther ? [...sectorsSorted, 'Other'] : sectorsSorted,
    };
  }, [rows]);

  if (!data.length) return <div className="empty">No funding rounds for this topic.</div>;
  return (
    <ResponsiveContainer width="100%" height={320}>
      <BarChart data={data} margin={{ top: 8, right: 8, left: 8, bottom: 0 }}>
        <CartesianGrid vertical={false} stroke={theme.grid} />
        <XAxis dataKey="year" tick={{ fill: theme.axis, fontSize: 12 }} axisLine={{ stroke: theme.grid }} tickLine={false} />
        <YAxis tickFormatter={(v: number) => formatMoney(v)} tick={{ fill: theme.axis, fontSize: 12 }} axisLine={false} tickLine={false} width={64} />
        <Tooltip
          formatter={(v, name) => [formatMoney(Number(v)), String(name)]}
          contentStyle={{ background: theme.surface, border: `1px solid ${theme.grid}`, borderRadius: 8, color: theme.text }}
          labelStyle={{ color: theme.text, fontWeight: 600 }}
          itemStyle={{ color: theme.text }}
          cursor={{ fill: theme.grid, fillOpacity: 0.5 }}
        />
        <Legend wrapperStyle={{ fontSize: 12, color: theme.axis }} />
        {sectors.map((s, i) => (
          <Bar
            key={s}
            dataKey={s}
            stackId="funding"
            fill={s === 'Other' ? theme.other : theme.series[i % theme.series.length]}
            stroke={theme.surface}
            strokeWidth={1}
            maxBarSize={48}
          />
        ))}
      </BarChart>
    </ResponsiveContainer>
  );
}

export function SectorChart({ rows }: { rows: SectorRow[] }) {
  const theme = useChartTheme();
  const data = useMemo(
    () =>
      [...rows]
        .map((r) => ({ ...r, sector: r.sector ?? 'Unknown', total_funding: r.total_funding ?? 0 }))
        .sort((a, b) => b.total_funding - a.total_funding),
    [rows],
  );
  if (!data.length) return <div className="empty">No sector data.</div>;
  return (
    <div className="sector-layout">
      <ResponsiveContainer width="100%" height={Math.max(200, data.length * 28 + 40)}>
        <BarChart data={data} layout="vertical" margin={{ top: 4, right: 24, left: 8, bottom: 4 }}>
          <CartesianGrid horizontal={false} stroke={theme.grid} />
          <XAxis type="number" tickFormatter={(v: number) => formatMoney(v)} tick={{ fill: theme.axis, fontSize: 12 }} axisLine={false} tickLine={false} />
          <YAxis type="category" dataKey="sector" width={140} tick={{ fill: theme.axis, fontSize: 12 }} axisLine={false} tickLine={false} />
          <Tooltip
            formatter={(v) => [formatMoney(Number(v)), 'Total funding']}
            contentStyle={{ background: theme.surface, border: `1px solid ${theme.grid}`, borderRadius: 8, color: theme.text }}
            labelStyle={{ color: theme.text, fontWeight: 600 }}
          itemStyle={{ color: theme.text }}
            cursor={{ fill: theme.grid, fillOpacity: 0.5 }}
          />
          <Bar dataKey="total_funding" fill={theme.series[0]} radius={[0, 4, 4, 0]} maxBarSize={18} />
        </BarChart>
      </ResponsiveContainer>
      <div className="table-scroll">
        <table className="table table-compact">
          <thead>
            <tr>
              <th>Sector</th>
              <th className="num">Companies</th>
              <th className="num">Total funding</th>
              <th className="num">Avg hiring growth</th>
            </tr>
          </thead>
          <tbody>
            {data.map((r) => (
              <tr key={r.sector}>
                <td>{r.sector}</td>
                <td className="num">{r.companies}</td>
                <td className="num">{formatMoney(r.total_funding)}</td>
                <td className="num">{formatPct(r.avg_hiring_growth, 1)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
