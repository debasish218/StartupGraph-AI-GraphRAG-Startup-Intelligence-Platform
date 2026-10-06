import { useState } from 'react';
import { api } from '../api';
import { CompanyDrawer } from '../components/CompanyDrawer';
import { Card, Chips, Empty, ErrorBox, Loading } from '../components/Status';
import { TopicSelect } from '../components/TopicSelect';
import { formatMoney, formatScore } from '../format';
import { useAsync } from '../hooks';
import { ScoreBar } from '../components/ScoreBar';

export function DiscoverPage() {
  const [invTopic, setInvTopic] = useState('');
  const [recTopic, setRecTopic] = useState('');
  const [selected, setSelected] = useState<string | null>(null);
  const investors = useAsync(() => api.discoverInvestors(invTopic), [invTopic]);
  const recs = useAsync(() => api.recommendations(recTopic, 10), [recTopic]);

  return (
    <div className="page">
      <header className="page-head">
        <h1>Discover</h1>
        <p className="muted">Find the most active investors in a space and get startup recommendations.</p>
      </header>

      <Card
        title="Investor discovery"
        actions={
          <label className="field-inline">
            <span className="small muted">Topic</span>
            <TopicSelect value={invTopic} onChange={setInvTopic} />
          </label>
        }
      >
        <ErrorBox error={investors.error} onRetry={investors.reload} />
        {investors.loading ? (
          <Loading />
        ) : investors.data && investors.data.length === 0 ? (
          <Empty>No investors found for this topic.</Empty>
        ) : (
          investors.data && (
            <div className="table-scroll">
              <table className="table">
                <thead>
                  <tr>
                    <th className="num">#</th>
                    <th>Investor</th>
                    <th>Type</th>
                    <th className="num">Startups backed</th>
                    <th className="num">Rounds</th>
                    <th className="num">Led</th>
                    <th className="num">Round volume</th>
                    <th>Portfolio</th>
                  </tr>
                </thead>
                <tbody>
                  {investors.data.map((inv, i) => (
                    <tr key={inv.id}>
                      <td className="num muted">{i + 1}</td>
                      <td>
                        <strong>{inv.investor}</strong>
                        {inv.quality !== null && inv.quality !== undefined && <div className="muted small">quality {formatScore(inv.quality)}</div>}
                      </td>
                      <td>{inv.type ?? '—'}</td>
                      <td className="num">{inv.startups_backed}</td>
                      <td className="num">{inv.rounds}</td>
                      <td className="num">{inv.rounds_led}</td>
                      <td className="num">{formatMoney(inv.round_volume)}</td>
                      <td className="portfolio-cell">
                        <Chips items={inv.portfolio} />
                        {inv.sectors?.length > 0 && <div className="muted small">{inv.sectors.join(' · ')}</div>}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )
        )}
      </Card>

      <Card
        title="Recommendations"
        actions={
          <label className="field-inline">
            <span className="small muted">Topic</span>
            <TopicSelect value={recTopic} onChange={setRecTopic} />
          </label>
        }
      >
        <ErrorBox error={recs.error} onRetry={recs.reload} />
        {recs.loading ? (
          <Loading />
        ) : recs.data && recs.data.length === 0 ? (
          <Empty>No recommendations for this topic.</Empty>
        ) : (
          <div className="rec-grid">
            {(recs.data ?? []).map((r, i) => (
              <article key={r.company_id} className="rec-card">
                <header className="row-between">
                  <div>
                    <span className="muted small">#{i + 1}</span>{' '}
                    <button type="button" className="link-btn strong" onClick={() => setSelected(r.company_id)}>
                      {r.name}
                    </button>
                    <div className="muted small">
                      {r.sector ?? '—'} · {formatMoney(r.total_funding)}
                    </div>
                  </div>
                  <div className="big-score" title="Startup score">
                    {formatScore(r.score)}
                  </div>
                </header>
                <ScoreBar label="Growth" value={r.growth_score} color="var(--series-3)" compact />
                <div className="kv">
                  <span className="muted small">Investors</span>
                  <Chips items={r.investors?.slice(0, 8)} />
                </div>
                <div className="kv">
                  <span className="muted small">Similar companies</span>
                  <Chips items={r.similar_companies?.map((s) => `${s.name} · ${formatScore(s.score)}`)} />
                </div>
              </article>
            ))}
          </div>
        )}
      </Card>
      <CompanyDrawer id={selected} onClose={() => setSelected(null)} />
    </div>
  );
}
