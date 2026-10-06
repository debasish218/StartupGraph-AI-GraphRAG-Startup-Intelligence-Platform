import type { Ranking, RankingWeights } from '../api';
import { formatMoney, formatPct, formatScore } from '../format';
import { COMPONENTS, COMPONENT_LABEL, COMPONENT_VAR, DEFAULT_WEIGHTS, ScoreBar, StackedScore } from './ScoreBar';
import { Empty } from './Status';

export function RankingTable({
  rankings,
  weights = DEFAULT_WEIGHTS,
  onSelect,
}: {
  rankings: Ranking[];
  weights?: RankingWeights;
  onSelect?: (r: Ranking) => void;
}) {
  if (!rankings.length) return <Empty>No ranked companies.</Empty>;
  return (
    <div className="table-scroll">
      <table className="table">
        <thead>
          <tr>
            <th className="num">#</th>
            <th>Company</th>
            <th>Sector</th>
            <th className="num">Total funding</th>
            <th>Score</th>
            {COMPONENTS.map((k) => (
              <th key={k}>
                <span className="legend-swatch" style={{ background: COMPONENT_VAR[k] }} /> {COMPONENT_LABEL[k]}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rankings.map((r, i) => (
            <tr key={r.company_id} className={onSelect ? 'clickable' : undefined} onClick={onSelect ? () => onSelect(r) : undefined}>
              <td className="num muted">{i + 1}</td>
              <td>
                {onSelect ? (
                  <button type="button" className="link-btn strong" onClick={(e) => { e.stopPropagation(); onSelect(r); }}>
                    {r.name}
                  </button>
                ) : (
                  <strong>{r.name}</strong>
                )}
                <div className="muted small">
                  {r.news_articles ?? 0} articles · growth {formatPct(r.employee_growth_pct)}
                </div>
              </td>
              <td>{r.sector ?? '—'}</td>
              <td className="num">{formatMoney(r.total_funding)}</td>
              <td className="score-cell">
                <div className="score-total">{formatScore(r.score, 1)}</div>
                <StackedScore parts={r} weights={weights} />
              </td>
              {COMPONENTS.map((k) => (
                <td key={k} className="bar-cell">
                  <ScoreBar value={r[k]} color={COMPONENT_VAR[k]} compact />
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
