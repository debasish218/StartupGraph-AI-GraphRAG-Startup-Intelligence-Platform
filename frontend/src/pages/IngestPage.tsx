import { useState, type FormEvent, type ReactNode } from 'react';
import {
  api,
  errorMessage,
  getApiKey,
  setApiKey,
  type IngestArticleResponse,
  type IngestGithubResponse,
  type IngestRssResponse,
  type IngestYcResponse,
} from '../api';
import { JsonView } from '../components/JsonView';
import { Badge, Card, Chips, ErrorBox, Loading } from '../components/Status';
import { formatMoney, formatNumber, humanize } from '../format';
import { useAsync } from '../hooks';

/** Small helper managing loading/error/result for a single action. */
function useAction<T>() {
  const [result, setResult] = useState<T | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const run = async (fn: () => Promise<T>) => {
    setLoading(true);
    setError(null);
    try {
      setResult(await fn());
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setLoading(false);
    }
  };
  return { result, loading, error, run };
}

export function IngestPage() {
  const stats = useAsync(() => api.stats(), []);
  const [key, setKey] = useState(getApiKey());
  const [saved, setSaved] = useState(false);

  const saveKey = (e: FormEvent) => {
    e.preventDefault();
    setApiKey(key.trim());
    setSaved(true);
    window.setTimeout(() => setSaved(false), 1500);
  };

  return (
    <div className="page">
      <header className="page-head">
        <h1>Ingestion</h1>
        <p className="muted">Feed new articles, RSS feeds, YC companies and GitHub data into the graph and vector store.</p>
      </header>

      <Card title="Platform stats" actions={<button type="button" className="btn btn-small" onClick={stats.reload}>Refresh</button>}>
        <ErrorBox error={stats.error} onRetry={stats.reload} />
        {stats.loading && !stats.data ? (
          <Loading />
        ) : (
          stats.data && (
            <div className="stats">
              <div className="stat-group">
                <h4 className="section-title">Graph</h4>
                <div className="stat-tiles">
                  {Object.entries(stats.data.graph).map(([k, v]) => (
                    <div key={k} className="stat-tile">
                      <span className="stat-value">{formatNumber(v)}</span>
                      <span className="stat-label">{humanize(k)}</span>
                    </div>
                  ))}
                </div>
              </div>
              <div className="stat-group">
                <h4 className="section-title">Documents</h4>
                <div className="stat-tiles">
                  {Object.entries(stats.data.documents).map(([k, v]) => (
                    <div key={k} className="stat-tile">
                      <span className="stat-value">{formatNumber(v)}</span>
                      <span className="stat-label">{humanize(k)}</span>
                    </div>
                  ))}
                </div>
              </div>
              <div className="row-gap wrap">
                <Badge tone="blue">LLM: {stats.data.llm_provider}</Badge>
                <Badge tone="violet">Embeddings: {stats.data.embedding_model}</Badge>
              </div>
            </div>
          )
        )}
      </Card>

      <Card title="API key">
        <form className="row-gap wrap" onSubmit={saveKey}>
          <input
            className="input input-key"
            type="password"
            autoComplete="off"
            placeholder="X-API-Key for ingestion endpoints"
            value={key}
            onChange={(e) => setKey(e.target.value)}
          />
          <button type="submit" className="btn">
            {saved ? 'Saved ✓' : 'Save'}
          </button>
          <span className="muted small">Stored in this browser only and sent as the X-API-Key header.</span>
        </form>
      </Card>

      <div className="grid-2">
        <ArticleForm onDone={stats.reload} />
        <div className="stack">
          <RssCard onDone={stats.reload} />
          <YcCard onDone={stats.reload} />
          <GithubCard onDone={stats.reload} />
        </div>
      </div>
    </div>
  );
}

function ArticleForm({ onDone }: { onDone: () => void }) {
  const [title, setTitle] = useState('');
  const [body, setBody] = useState('');
  const [url, setUrl] = useState('');
  const [publishedAt, setPublishedAt] = useState('');
  const a = useAction<IngestArticleResponse>();

  const submit = (e: FormEvent) => {
    e.preventDefault();
    void a
      .run(() =>
        api.ingestArticle({
          title: title.trim(),
          body: body.trim(),
          url: url.trim() || undefined,
          published_at: publishedAt || undefined,
        }),
      )
      .then(onDone);
  };

  return (
    <Card title="Ingest news article">
      <form className="form" onSubmit={submit}>
        <label>
          <span>Title</span>
          <input className="input" required value={title} onChange={(e) => setTitle(e.target.value)} placeholder="Acme AI raises $50M Series B led by Sequoia" />
        </label>
        <label>
          <span>Body</span>
          <textarea className="input" required rows={8} value={body} onChange={(e) => setBody(e.target.value)} placeholder="Paste the article text…" />
        </label>
        <div className="form-row">
          <label>
            <span>URL</span>
            <input className="input" type="url" value={url} onChange={(e) => setUrl(e.target.value)} placeholder="https://…" />
          </label>
          <label>
            <span>Published</span>
            <input className="input" type="date" value={publishedAt} onChange={(e) => setPublishedAt(e.target.value)} />
          </label>
        </div>
        <button type="submit" className="btn btn-primary" disabled={a.loading || !title.trim() || !body.trim()}>
          {a.loading ? 'Ingesting…' : 'Ingest article'}
        </button>
      </form>
      <ErrorBox error={a.error} />
      {a.loading && <Loading label="Extracting events and updating graph…" />}
      {a.result && <ArticleResult r={a.result} />}
    </Card>
  );
}

function ArticleResult({ r }: { r: IngestArticleResponse }) {
  if (r.status === 'duplicate') return <div className="note">This article was already ingested (duplicate).</div>;
  return (
    <div className="result">
      <div className="row-gap wrap">
        <Badge tone="good">{r.status}</Badge>
        {r.sentiment !== undefined && r.sentiment !== null && (
          <Badge tone="neutral">sentiment {typeof r.sentiment === 'number' ? r.sentiment.toFixed(2) : r.sentiment}</Badge>
        )}
      </div>
      <h4 className="section-title">Mentions</h4>
      <Chips items={r.mentions} empty="No companies detected" />
      <h4 className="section-title">Detected events ({r.events?.length ?? 0})</h4>
      {r.events && r.events.length > 0 ? (
        <div className="events">
          {r.events.map((ev, i) => (
            <article key={i} className="event">
              <header className="row-gap wrap">
                <Badge tone="blue">{ev.type}</Badge>
                <strong>{ev.company ?? '—'}</strong>
                {ev.counterparty && <span>→ {ev.counterparty}</span>}
              </header>
              <dl className="facts facts-compact">
                {ev.amount != null && <Fact k="Amount">{formatMoney(ev.amount)}</Fact>}
                {ev.round_type && <Fact k="Round">{ev.round_type}</Fact>}
                {ev.lead_investors && ev.lead_investors.length > 0 && <Fact k="Lead">{ev.lead_investors.join(', ')}</Fact>}
                {ev.investors && ev.investors.length > 0 && <Fact k="Investors">{ev.investors.join(', ')}</Fact>}
                {ev.product && <Fact k="Product">{ev.product}</Fact>}
              </dl>
              {ev.evidence && <blockquote className="evidence">{ev.evidence}</blockquote>}
            </article>
          ))}
        </div>
      ) : (
        <p className="muted small">No events detected.</p>
      )}
      <h4 className="section-title">Graph updates ({r.graph_updates?.length ?? 0})</h4>
      {r.graph_updates && r.graph_updates.length > 0 ? <JsonView value={r.graph_updates} /> : <p className="muted small">No graph changes.</p>}
    </div>
  );
}

function Fact({ k, children }: { k: string; children: ReactNode }) {
  return (
    <div>
      <dt>{k}</dt>
      <dd>{children}</dd>
    </div>
  );
}

function RssCard({ onDone }: { onDone: () => void }) {
  const [max, setMax] = useState(20);
  const a = useAction<IngestRssResponse>();
  return (
    <Card title="RSS feeds">
      <div className="row-gap wrap">
        <label className="small">
          Max items{' '}
          <input className="input input-num" type="number" min={1} max={200} value={max} onChange={(e) => setMax(Number(e.target.value) || 20)} />
        </label>
        <button type="button" className="btn btn-primary" disabled={a.loading} onClick={() => void a.run(() => api.ingestRss(max)).then(onDone)}>
          {a.loading ? 'Pulling…' : 'Pull RSS feeds'}
        </button>
      </div>
      <ErrorBox error={a.error} />
      {a.loading && <Loading label="Fetching and processing feeds…" />}
      {a.result && (
        <div className="result">
          <div className="row-gap wrap">
            <Badge tone="good">ingested {a.result.ingested}</Badge>
            <Badge tone="neutral">duplicates {a.result.duplicates}</Badge>
            <Badge tone={countOf(a.result.errors) ? 'bad' : 'neutral'}>errors {countOf(a.result.errors)}</Badge>
            <Badge tone="blue">graph updates {countOf(a.result.graph_updates)}</Badge>
          </div>
          {a.result.items?.length > 0 && (
            <details>
              <summary className="small">Items ({a.result.items.length})</summary>
              <JsonView value={a.result.items} />
            </details>
          )}
        </div>
      )}
    </Card>
  );
}

function countOf(v: number | unknown[] | null | undefined): number {
  if (Array.isArray(v)) return v.length;
  return typeof v === 'number' ? v : 0;
}

function YcCard({ onDone }: { onDone: () => void }) {
  const [industry, setIndustry] = useState('');
  const [tag, setTag] = useState('');
  const [batch, setBatch] = useState('');
  const [limit, setLimit] = useState(50);
  const a = useAction<IngestYcResponse>();
  const submit = (e: FormEvent) => {
    e.preventDefault();
    void a
      .run(() =>
        api.ingestYc({
          industry: industry.trim() || undefined,
          tag: tag.trim() || undefined,
          batch: batch.trim() || undefined,
          limit,
        }),
      )
      .then(onDone);
  };
  return (
    <Card title="Y Combinator import">
      <form className="form" onSubmit={submit}>
        <div className="form-row">
          <label>
            <span>Industry</span>
            <input className="input" value={industry} onChange={(e) => setIndustry(e.target.value)} placeholder="B2B" />
          </label>
          <label>
            <span>Tag</span>
            <input className="input" value={tag} onChange={(e) => setTag(e.target.value)} placeholder="Artificial Intelligence" />
          </label>
        </div>
        <div className="form-row">
          <label>
            <span>Batch</span>
            <input className="input" value={batch} onChange={(e) => setBatch(e.target.value)} placeholder="W24" />
          </label>
          <label>
            <span>Limit</span>
            <input className="input" type="number" min={1} max={1000} value={limit} onChange={(e) => setLimit(Number(e.target.value) || 50)} />
          </label>
        </div>
        <button type="submit" className="btn btn-primary" disabled={a.loading}>
          {a.loading ? 'Importing…' : 'Import YC companies'}
        </button>
      </form>
      <ErrorBox error={a.error} />
      {a.loading && <Loading label="Importing…" />}
      {a.result && (
        <div className="row-gap wrap result">
          <Badge tone="good">imported {a.result.imported}</Badge>
          <Badge tone="neutral">documents added {a.result.documents_added}</Badge>
        </div>
      )}
    </Card>
  );
}

function GithubCard({ onDone }: { onDone: () => void }) {
  const a = useAction<IngestGithubResponse>();
  return (
    <Card title="GitHub enrichment">
      <p className="muted small">Pull repository stats and technologies for companies with a known GitHub org.</p>
      <button type="button" className="btn btn-primary" disabled={a.loading} onClick={() => void a.run(() => api.ingestGithub()).then(onDone)}>
        {a.loading ? 'Enriching…' : 'Run GitHub enrichment'}
      </button>
      <ErrorBox error={a.error} />
      {a.loading && <Loading label="Calling GitHub…" />}
      {a.result && (
        <div className="result">
          <Badge tone="good">updated {a.result.updated}</Badge>
          {a.result.errors?.length > 0 && (
            <ul className="error-list small">
              {a.result.errors.map((e, i) => (
                <li key={i}>{e}</li>
              ))}
            </ul>
          )}
        </div>
      )}
    </Card>
  );
}
