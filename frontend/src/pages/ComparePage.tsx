import { useEffect, useState, type ReactNode } from 'react';
import { api, errorMessage, type CompareResponse, type EntityHit, type SimilarCompany } from '../api';
import { FundingRoundsTable } from '../components/CompanyDrawer';
import { EntityMultiPicker, EntityPicker } from '../components/EntityPicker';
import { COMPONENTS, COMPONENT_LABEL, COMPONENT_VAR, ScoreBar } from '../components/ScoreBar';
import { SimilarList } from '../components/SimilarList';
import { Card, Chips, Empty, ErrorBox, Loading } from '../components/Status';
import { formatMoney, formatNumber, formatPct, formatScore } from '../format';

export function ComparePage() {
  const [picked, setPicked] = useState<EntityHit[]>([
    { id: 'openai', name: 'OpenAI', labels: ['Company'] },
    { id: 'anthropic', name: 'Anthropic', labels: ['Company'] },
  ]);
  const [data, setData] = useState<CompareResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const run = async (ids: string[]) => {
    if (ids.length < 2) return;
    setLoading(true);
    setError(null);
    try {
      setData(await api.compare(ids));
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void run(['openai', 'anthropic']);
  }, []);

  return (
    <div className="page">
      <header className="page-head">
        <h1>Compare companies</h1>
        <p className="muted">Side-by-side profiles, funding and scores for 2–5 companies.</p>
      </header>
      <Card title="Companies">
        <div className="rel-controls">
          <EntityMultiPicker value={picked} onChange={setPicked} max={5} label="Company" placeholder="Add company…" />
          <button type="button" className="btn btn-primary" disabled={picked.length < 2 || loading} onClick={() => void run(picked.map((p) => p.id))}>
            {loading ? 'Comparing…' : 'Compare'}
          </button>
        </div>
        {picked.length < 2 && <p className="muted small">Pick at least two companies.</p>}
      </Card>

      <ErrorBox error={error} onRetry={() => void run(picked.map((p) => p.id))} />
      {loading && <Loading label="Loading profiles…" />}
      {data && !loading && <CompareGrid data={data} />}

      <SimilarPanel />
    </div>
  );
}

function CompareGrid({ data }: { data: CompareResponse }) {
  const cs = data.companies;
  if (!cs.length) return <Empty>No companies found.</Empty>;
  const row = (label: string, render: (c: CompareResponse['companies'][number]) => ReactNode) => (
    <div className="cmp-row" key={label}>
      <div className="cmp-label">{label}</div>
      {cs.map((c) => (
        <div className="cmp-cell" key={c.id}>
          {render(c)}
        </div>
      ))}
    </div>
  );
  const ic = data.in_common;
  return (
    <>
      <Card title="Side by side">
        <div className="cmp-scroll">
          <div className="cmp" style={{ gridTemplateColumns: `140px repeat(${cs.length}, minmax(200px, 1fr))` }}>
            <div className="cmp-row cmp-head">
              <div className="cmp-label" />
              {cs.map((c) => (
                <div className="cmp-cell" key={c.id}>
                  <h3>{c.name}</h3>
                  {c.website && (
                    <a className="small" href={c.website.startsWith('http') ? c.website : `https://${c.website}`} target="_blank" rel="noreferrer">
                      {c.website}
                    </a>
                  )}
                </div>
              ))}
            </div>
            {row('Description', (c) => <span className="small">{c.description ?? '—'}</span>)}
            {row('Sector', (c) => c.sector ?? '—')}
            {row('Country', (c) => c.country ?? '—')}
            {row('Founded', (c) => c.founded_year ?? '—')}
            {row('Employees', (c) => formatNumber(c.employees))}
            {row('Hiring growth', (c) => formatPct(c.employee_growth_pct))}
            {row('Total funding', (c) => <strong>{formatMoney(c.total_funding)}</strong>)}
            {row('Score', (c) =>
              c.score ? (
                <div>
                  <div className="big-score">{formatScore(c.score.score, 1)}</div>
                  {COMPONENTS.map((k) => (
                    <ScoreBar key={k} label={COMPONENT_LABEL[k]} value={c.score![k]} color={COMPONENT_VAR[k]} compact />
                  ))}
                </div>
              ) : (
                <span className="muted">Not scored</span>
              ),
            )}
            {row('Founders', (c) => <Chips items={c.founders} />)}
            {row('Investors', (c) => <Chips items={c.investors} />)}
            {row('Technologies', (c) => <Chips items={c.technologies} />)}
            {row('Competitors', (c) => <Chips items={c.competitors} />)}
            {row('Partners', (c) => <Chips items={c.partners} />)}
            {row('Funding rounds', (c) => <FundingRoundsTable rounds={c.funding_rounds} />)}
          </div>
        </div>
      </Card>
      <Card title="In common">
        <div className="common-grid">
          {(['investors', 'technologies', 'competitors', 'partners'] as const).map((k) => (
            <div key={k}>
              <h4 className="section-title">{k[0].toUpperCase() + k.slice(1)}</h4>
              <Chips items={ic?.[k]} empty="None shared" />
            </div>
          ))}
        </div>
      </Card>
    </>
  );
}

function SimilarPanel() {
  const [company, setCompany] = useState<EntityHit>({ id: 'anthropic', name: 'Anthropic', labels: ['Company'] });
  const [different, setDifferent] = useState(true);
  const [items, setItems] = useState<SimilarCompany[] | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    api
      .similar(company.id, different)
      .then((r) => !cancelled && setItems(r))
      .catch((e: unknown) => !cancelled && setError(errorMessage(e)))
      .finally(() => !cancelled && setLoading(false));
    return () => {
      cancelled = true;
    };
  }, [company.id, different]);

  return (
    <Card
      title={
        <>
          Companies similar to <span className="accent">{company.name}</span>
        </>
      }
      actions={
        <div className="toolbar">
          <div className="toolbar-picker">
            <EntityPicker label="Company" placeholder="Choose company…" onSelect={setCompany} />
          </div>
          <label className="check small">
            <input type="checkbox" checked={different} onChange={(e) => setDifferent(e.target.checked)} /> Different investors only
          </label>
        </div>
      }
    >
      <ErrorBox error={error} />
      {loading ? <Loading /> : items && <SimilarList items={items} />}
    </Card>
  );
}
