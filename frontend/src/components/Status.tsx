import type { ReactNode } from 'react';

export function Loading({ label = 'Loading…' }: { label?: string }) {
  return (
    <div className="loading" role="status">
      <span className="spinner" aria-hidden="true" />
      <span>{label}</span>
    </div>
  );
}

export function ErrorBox({ error, onRetry }: { error: string | null; onRetry?: () => void }) {
  if (!error) return null;
  return (
    <div className="error-box" role="alert">
      <strong>Error.</strong> <span>{error}</span>
      {onRetry && (
        <button type="button" className="btn btn-small" onClick={onRetry}>
          Retry
        </button>
      )}
    </div>
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return <div className="empty">{children}</div>;
}

export function Card({
  title,
  actions,
  children,
  className,
}: {
  title?: ReactNode;
  actions?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section className={`card ${className ?? ''}`}>
      {(title || actions) && (
        <header className="card-header">
          {title && <h2 className="card-title">{title}</h2>}
          {actions && <div className="card-actions">{actions}</div>}
        </header>
      )}
      <div className="card-body">{children}</div>
    </section>
  );
}

export function Chips({ items, onClick, empty = '—' }: { items: string[] | null | undefined; onClick?: (s: string) => void; empty?: string }) {
  if (!items || items.length === 0) return <span className="muted">{empty}</span>;
  return (
    <div className="chips">
      {items.map((s, i) =>
        onClick ? (
          <button type="button" key={`${s}-${i}`} className="chip chip-btn" onClick={() => onClick(s)}>
            {s}
          </button>
        ) : (
          <span key={`${s}-${i}`} className="chip">
            {s}
          </span>
        ),
      )}
    </div>
  );
}

export function Badge({ children, tone = 'neutral', title }: { children: ReactNode; tone?: string; title?: string }) {
  return (
    <span className={`badge badge-${tone}`} title={title}>
      {children}
    </span>
  );
}
