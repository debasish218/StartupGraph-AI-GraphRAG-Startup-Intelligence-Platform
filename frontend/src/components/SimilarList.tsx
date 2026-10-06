import type { SimilarCompany } from '../api';
import { formatMoney, formatScore } from '../format';
import { ScoreBar } from './ScoreBar';
import { Chips, Empty } from './Status';

const SIM_COMPONENTS = ['embedding', 'technology', 'investor', 'sector'] as const;
const SIM_COLOR: Record<(typeof SIM_COMPONENTS)[number], string> = {
  embedding: 'var(--series-1)',
  technology: 'var(--series-2)',
  investor: 'var(--series-3)',
  sector: 'var(--series-4)',
};

export function SimilarList({ items, onSelect }: { items: SimilarCompany[]; onSelect?: (id: string) => void }) {
  if (!items.length) return <Empty>No similar companies found.</Empty>;
  return (
    <div className="similar-grid">
      {items.map((s) => (
        <article key={s.id} className="similar-card">
          <header className="row-between">
            <div>
              {onSelect ? (
                <button type="button" className="link-btn strong" onClick={() => onSelect(s.id)}>
                  {s.name}
                </button>
              ) : (
                <strong>{s.name}</strong>
              )}
              <div className="muted small">
                {s.sector ?? '—'} · {formatMoney(s.total_funding)}
              </div>
            </div>
            <div className="big-score" title="Similarity score">
              {formatScore(s.score)}
            </div>
          </header>
          <div className="mini-bars">
            {SIM_COMPONENTS.map((k) => (
              <ScoreBar key={k} label={k} value={s.components?.[k]} color={SIM_COLOR[k]} compact />
            ))}
          </div>
          {s.shared_technologies.length > 0 && (
            <div className="kv">
              <span className="muted small">Shared tech</span>
              <Chips items={s.shared_technologies} />
            </div>
          )}
          {s.shared_investors.length > 0 && (
            <div className="kv">
              <span className="muted small">Shared investors</span>
              <Chips items={s.shared_investors} />
            </div>
          )}
          <div className="kv">
            <span className="muted small">Investors</span>
            <Chips items={s.investors.slice(0, 8)} />
          </div>
        </article>
      ))}
    </div>
  );
}
