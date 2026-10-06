import { formatScore } from '../format';
import type { RankingWeights } from '../api';

export const COMPONENTS = ['funding', 'news', 'hiring', 'investor_quality'] as const;
export type ComponentKey = (typeof COMPONENTS)[number];

export const COMPONENT_LABEL: Record<ComponentKey, string> = {
  funding: 'Funding',
  news: 'News',
  hiring: 'Hiring',
  investor_quality: 'Investor quality',
};

export const COMPONENT_VAR: Record<ComponentKey, string> = {
  funding: 'var(--series-1)',
  news: 'var(--series-2)',
  hiring: 'var(--series-3)',
  investor_quality: 'var(--series-4)',
};

export const DEFAULT_WEIGHTS: RankingWeights = { funding: 0.35, news: 0.25, hiring: 0.2, investor_quality: 0.2 };

/** Horizontal bar for a 0..1 value with numeric label. */
export function ScoreBar({ value, color = 'var(--accent)', label, compact }: { value: number | null | undefined; color?: string; label?: string; compact?: boolean }) {
  const v = Math.max(0, Math.min(1, value ?? 0));
  return (
    <div className={`scorebar ${compact ? 'scorebar-compact' : ''}`} title={`${label ? label + ': ' : ''}${formatScore(value, 1)} / 100`}>
      {label && <span className="scorebar-label">{label}</span>}
      <span className="scorebar-track">
        <span className="scorebar-fill" style={{ width: `${v * 100}%`, background: color }} />
      </span>
      <span className="scorebar-value">{formatScore(value)}</span>
    </div>
  );
}

/** Stacked bar showing each component's weighted contribution to the total score. */
export function StackedScore({ parts, weights = DEFAULT_WEIGHTS }: { parts: Record<ComponentKey, number>; weights?: RankingWeights }) {
  return (
    <div className="stacked" role="img" aria-label={COMPONENTS.map((k) => `${COMPONENT_LABEL[k]} ${formatScore(parts[k])}`).join(', ')}>
      {COMPONENTS.map((k) => {
        const contrib = (parts[k] ?? 0) * weights[k];
        return (
          <span
            key={k}
            className="stacked-seg"
            style={{ width: `${contrib * 100}%`, background: COMPONENT_VAR[k] }}
            title={`${COMPONENT_LABEL[k]}: ${formatScore(parts[k], 1)} × ${weights[k]} = ${formatScore(contrib, 1)}`}
          />
        );
      })}
    </div>
  );
}

export function ComponentLegend() {
  return (
    <div className="legend-row">
      {COMPONENTS.map((k) => (
        <span key={k} className="legend-item">
          <span className="legend-swatch" style={{ background: COMPONENT_VAR[k] }} />
          {COMPONENT_LABEL[k]}
        </span>
      ))}
    </div>
  );
}

export function Formula({ weights }: { weights: RankingWeights }) {
  return (
    <code className="formula">
      score = {COMPONENTS.map((k, i) => (
        <span key={k}>
          {i > 0 && ' + '}
          {weights[k]}·<span style={{ color: COMPONENT_VAR[k], fontWeight: 600 }}>{k}</span>
        </span>
      ))}
    </code>
  );
}
