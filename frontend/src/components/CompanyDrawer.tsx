import { useEffect } from 'react';
import { api } from '../api';
import { formatDate, formatMoney, formatNumber, formatPct, formatScore } from '../format';
import { useAsync } from '../hooks';
import { COMPONENTS, COMPONENT_LABEL, COMPONENT_VAR, ScoreBar } from './ScoreBar';
import { Chips, Empty, ErrorBox, Loading } from './Status';

export function CompanyDrawer({ id, onClose }: { id: string | null; onClose: () => void }) {
  const { data, loading, error, reload } = useAsync(() => api.company(id!), [id], id !== null);

  useEffect(() => {
    if (!id) return;
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && onClose();
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [id, onClose]);

  if (!id) return null;
  const p = data?.profile;
  return (
    <>
      <div className="scrim scrim-drawer" onClick={onClose} />
      <aside className="drawer" role="dialog" aria-modal="true" aria-label="Company details">
        <header className="drawer-head">
          <h2>{p?.name ?? id}</h2>
          <button type="button" className="icon-btn" onClick={onClose} aria-label="Close">
            ×
          </button>
        </header>
        <div className="drawer-body">
          {loading && <Loading />}
          <ErrorBox error={error} onRetry={reload} />
          {p && !loading && (
            <>
              {p.description && <p>{p.description}</p>}
              <dl className="facts">
                <div><dt>Sector</dt><dd>{p.sector ?? '—'}</dd></div>
                <div><dt>Country</dt><dd>{p.country ?? '—'}</dd></div>
                <div><dt>Founded</dt><dd>{p.founded_year ?? '—'}</dd></div>
                <div><dt>Employees</dt><dd>{formatNumber(p.employees)}</dd></div>
                <div><dt>Hiring growth</dt><dd>{formatPct(p.employee_growth_pct)}</dd></div>
                <div><dt>Total funding</dt><dd>{formatMoney(p.total_funding)}</dd></div>
                {p.website && (
                  <div>
                    <dt>Website</dt>
                    <dd>
                      <a href={p.website.startsWith('http') ? p.website : `https://${p.website}`} target="_blank" rel="noreferrer">
                        {p.website}
                      </a>
                    </dd>
                  </div>
                )}
              </dl>
              {data?.score && (
                <section>
                  <h3 className="section-title">
                    Startup score <span className="big-score inline">{formatScore(data.score.score, 1)}</span>
                  </h3>
                  {COMPONENTS.map((k) => (
                    <ScoreBar key={k} label={COMPONENT_LABEL[k]} value={data.score![k]} color={COMPONENT_VAR[k]} />
                  ))}
                </section>
              )}
              <section>
                <h3 className="section-title">Founders</h3>
                <Chips items={p.founders} />
                <h3 className="section-title">Investors</h3>
                <Chips items={p.investors} />
                {p.lead_investors.length > 0 && (
                  <>
                    <h3 className="section-title">Lead investors</h3>
                    <Chips items={p.lead_investors} />
                  </>
                )}
                <h3 className="section-title">Technologies</h3>
                <Chips items={p.technologies} />
                <h3 className="section-title">Competitors</h3>
                <Chips items={p.competitors} />
                {p.partners.length > 0 && (
                  <>
                    <h3 className="section-title">Partners</h3>
                    <Chips items={p.partners} />
                  </>
                )}
                {(p.acquisitions.length > 0 || p.acquired_by.length > 0) && (
                  <>
                    <h3 className="section-title">M&amp;A</h3>
                    {p.acquisitions.length > 0 && <div className="small">Acquired: {p.acquisitions.join(', ')}</div>}
                    {p.acquired_by.length > 0 && <div className="small">Acquired by: {p.acquired_by.join(', ')}</div>}
                  </>
                )}
              </section>
              <FundingRoundsTable rounds={p.funding_rounds} />
              <section>
                <h3 className="section-title">News</h3>
                {data?.news.length ? (
                  <ul className="news-list">
                    {data.news.map((n, i) => (
                      <li key={i}>
                        {n.url ? (
                          <a href={n.url} target="_blank" rel="noreferrer">
                            {n.title}
                          </a>
                        ) : (
                          <strong>{n.title}</strong>
                        )}
                        <div className="muted small">
                          {formatDate(n.published_at)}
                          {n.sentiment !== null && n.sentiment !== undefined && <> · sentiment {typeof n.sentiment === 'number' ? n.sentiment.toFixed(2) : n.sentiment}</>}
                        </div>
                        {n.snippet && <p className="snippet">{n.snippet}</p>}
                      </li>
                    ))}
                  </ul>
                ) : (
                  <Empty>No news articles.</Empty>
                )}
              </section>
            </>
          )}
        </div>
      </aside>
    </>
  );
}

export function FundingRoundsTable({ rounds }: { rounds: { round: string | null; amount: number | null; date: string | null }[] }) {
  return (
    <section>
      <h3 className="section-title">Funding rounds</h3>
      {rounds.length ? (
        <table className="table table-compact">
          <thead>
            <tr>
              <th>Round</th>
              <th className="num">Amount</th>
              <th>Date</th>
            </tr>
          </thead>
          <tbody>
            {rounds.map((r, i) => (
              <tr key={i}>
                <td>{r.round ?? '—'}</td>
                <td className="num">{formatMoney(r.amount)}</td>
                <td>{formatDate(r.date)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : (
        <Empty>No funding rounds recorded.</Empty>
      )}
    </section>
  );
}
