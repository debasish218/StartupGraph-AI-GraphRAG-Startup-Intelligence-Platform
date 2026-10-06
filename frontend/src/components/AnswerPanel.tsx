import { useEffect, useState } from 'react';
import type { CypherRun, DocumentHit, QueryResponse, Source, TraceEntry } from '../api';
import { formatDate, formatScore, humanize } from '../format';
import { GraphView } from './GraphView';
import { JsonView } from './JsonView';
import { Markdown } from './Markdown';
import { PathsList } from './PathsList';
import { RankingTable } from './RankingTable';
import { SimilarList } from './SimilarList';
import { Badge, Empty } from './Status';
import { Tabs, type TabDef } from './Tabs';

const QUERY_TYPE_TONE: Record<string, string> = { graph: 'blue', vector: 'violet', hybrid: 'teal' };
const LEVEL_TONE: Record<string, string> = { high: 'good', medium: 'warn', low: 'bad' };

export function AnswerPanel({ response }: { response: QueryResponse }) {
  const r = response;
  const defaultTab = r.graph?.nodes?.length ? 'graph' : r.rankings?.length || r.similar?.length ? 'rankings' : 'sources';
  const [tab, setTab] = useState(defaultTab);
  const [highlight, setHighlight] = useState<string | null>(null);
  const [showConf, setShowConf] = useState(false);

  useEffect(() => {
    setTab(defaultTab);
    setHighlight(null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [response]);

  const tabs: TabDef[] = [
    { id: 'graph', label: 'Graph', count: r.graph?.nodes?.length ?? 0 },
    { id: 'paths', label: 'Paths', count: r.paths?.length ?? 0 },
    { id: 'sources', label: 'Sources', count: (r.sources?.length ?? 0) + (r.documents?.length ?? 0) },
    { id: 'rankings', label: 'Rankings', count: (r.rankings?.length ?? 0) + (r.similar?.length ?? 0) },
    { id: 'trace', label: 'Agent trace', count: r.trace?.length ?? 0 },
    { id: 'cypher', label: 'Cypher', count: r.cypher?.length ?? 0 },
  ];

  const onCite = (id: string) => {
    setTab('sources');
    setHighlight(id);
    window.setTimeout(() => document.getElementById(`source-${id}`)?.scrollIntoView({ behavior: 'smooth', block: 'center' }), 50);
  };

  const conf = r.confidence;
  return (
    <div className="answer">
      <div className="answer-meta">
        <Badge tone={QUERY_TYPE_TONE[r.query_type] ?? 'neutral'} title="Retrieval strategy">
          {r.query_type}
        </Badge>
        <Badge tone="neutral" title={r.classification_reason}>
          intent: {humanize(r.intent ?? 'unknown')}
        </Badge>
        {conf && (
          <button type="button" className={`badge badge-${LEVEL_TONE[conf.level] ?? 'neutral'} badge-btn`} onClick={() => setShowConf((s) => !s)} aria-expanded={showConf} title="Show confidence components">
            confidence {formatScore(conf.score)}% · {conf.level} {showConf ? '▴' : '▾'}
          </button>
        )}
        <Badge tone="neutral" title="Answer generator">
          {r.answer_mode === 'llm' ? 'LLM answer' : 'Template answer'}
        </Badge>
        <span className="muted small">{Math.round(r.latency_ms)} ms</span>
      </div>
      {showConf && conf && (
        <div className="conf-components">
          {Object.entries(conf.components ?? {}).map(([k, v]) => (
            <div key={k} className="conf-row">
              <span>{humanize(k)}</span>
              <span className="scorebar-track">
                <span className="scorebar-fill" style={{ width: `${Math.max(0, Math.min(1, v)) * 100}%`, background: 'var(--accent)' }} />
              </span>
              <span className="num">{formatScore(v)}</span>
            </div>
          ))}
          {r.classification_reason && <p className="muted small">Classification: {r.classification_reason}</p>}
        </div>
      )}

      <div className="answer-body">
        <Markdown text={r.answer || '_No answer generated._'} onCite={onCite} />
      </div>

      {r.notes?.map((n, i) => (
        <div key={i} className="note">
          {n}
        </div>
      ))}
      {r.errors?.map((e, i) => (
        <div key={i} className="error-box">
          {e}
        </div>
      ))}

      <EntitySummary response={r} />

      <Tabs tabs={tabs} active={tab} onChange={setTab} />
      <div className="tab-panel">
        {tab === 'graph' && <GraphView graph={r.graph} height={520} />}
        {tab === 'paths' && <PathsList paths={r.paths ?? []} />}
        {tab === 'sources' && <SourcesView sources={r.sources ?? []} documents={r.documents ?? []} highlight={highlight} />}
        {tab === 'rankings' && (
          <>
            {r.rankings?.length ? <RankingTable rankings={r.rankings} /> : !r.similar?.length && <Empty>No rankings for this question.</Empty>}
            {r.similar?.length > 0 && (
              <>
                <h3 className="section-title">Similar companies</h3>
                <SimilarList items={r.similar} />
              </>
            )}
          </>
        )}
        {tab === 'trace' && <TraceView trace={r.trace ?? []} />}
        {tab === 'cypher' && <CypherView runs={r.cypher ?? []} />}
      </div>
    </div>
  );
}

function EntitySummary({ response }: { response: QueryResponse }) {
  const e = response.entities;
  if (!e) return null;
  const groups: [string, string[]][] = [
    ['Companies', e.companies?.map((x) => x.name) ?? []],
    ['Investors', e.investors?.map((x) => x.name) ?? []],
    ['Founders', e.founders?.map((x) => x.name) ?? []],
    ['Technologies', e.technologies?.map((x) => x.name) ?? []],
    ['Employers', e.employers?.map((x) => x.name) ?? []],
    ['Topics', e.topics ?? []],
    ['Rounds', e.round_types ?? []],
  ];
  const filtered = groups.filter(([, v]) => v.length > 0);
  const dates = e.date_from || e.date_to ? `${e.date_from ?? '…'} → ${e.date_to ?? '…'}${e.date_strict ? ' (strict)' : ''}` : null;
  if (!filtered.length && !dates) return null;
  return (
    <div className="entity-summary">
      <span className="muted small">Resolved:</span>
      {filtered.map(([k, v]) => (
        <span key={k} className="entity-group">
          <span className="muted small">{k}</span>
          {v.map((x) => (
            <span key={x} className="chip chip-small">
              {x}
            </span>
          ))}
        </span>
      ))}
      {dates && (
        <span className="entity-group">
          <span className="muted small">Dates</span>
          <span className="chip chip-small">{dates}</span>
        </span>
      )}
    </div>
  );
}

function SourcesView({ sources, documents, highlight }: { sources: Source[]; documents: DocumentHit[]; highlight: string | null }) {
  if (!sources.length && !documents.length) return <Empty>No sources were used.</Empty>;
  return (
    <div className="sources">
      {sources.length > 0 && <h3 className="section-title">Cited sources</h3>}
      {sources.map((s) => (
        <article key={s.id} id={`source-${s.id}`} className={`source ${highlight === s.id ? 'highlight' : ''}`}>
          <span className={`cite ${s.id === 'G' ? 'cite-graph' : 'cite-doc'}`}>{s.id}</span>
          <div className="source-body">
            <div className="source-title">
              {s.url ? (
                <a href={s.url} target="_blank" rel="noreferrer">
                  {s.title}
                </a>
              ) : (
                s.title
              )}
            </div>
            <div className="muted small">
              {[s.type, s.source, s.published_at ? formatDate(s.published_at) : null, s.score != null ? `score ${s.score.toFixed(3)}` : null]
                .filter(Boolean)
                .join(' · ')}
            </div>
            {s.detail && s.detail.length > 0 && (
              <ul className="source-detail">
                {s.detail.map((d, i) => (
                  <li key={i}>{d}</li>
                ))}
              </ul>
            )}
          </div>
        </article>
      ))}
      {documents.length > 0 && <h3 className="section-title">Retrieved documents</h3>}
      {documents.map((d, i) => (
        <article key={`${d.title}-${i}`} className="doc">
          <div className="row-between">
            <div className="source-title">
              {d.url ? (
                <a href={d.url} target="_blank" rel="noreferrer">
                  {d.title}
                </a>
              ) : (
                d.title
              )}
            </div>
            <span className="doc-score" title="Similarity score">
              {d.score.toFixed(3)}
            </span>
          </div>
          <div className="muted small">
            {[d.doc_type, d.source, d.published_at ? formatDate(d.published_at) : null].filter(Boolean).join(' · ')}
            {d.company_ids.length > 0 && <> · {d.company_ids.join(', ')}</>}
          </div>
          <p className="snippet">{d.snippet}</p>
        </article>
      ))}
    </div>
  );
}

function TraceView({ trace }: { trace: TraceEntry[] }) {
  if (!trace.length) return <Empty>No trace recorded.</Empty>;
  const max = Math.max(1, ...trace.map((t) => t.ms ?? 0));
  const total = trace.reduce((s, t) => s + (t.ms ?? 0), 0);
  return (
    <div>
      <p className="muted small">Total agent time: {Math.round(total)} ms</p>
      <ol className="timeline">
        {trace.map((t, i) => {
          const { agent, ms, ...rest } = t;
          return (
            <li key={i} className="timeline-item">
              <div className="timeline-head">
                <span className="timeline-agent">{agent}</span>
                <span className="timeline-bar">
                  <span style={{ width: `${((ms ?? 0) / max) * 100}%` }} />
                </span>
                <span className="num small">{(ms ?? 0).toFixed(1)} ms</span>
              </div>
              {Object.keys(rest).length > 0 && <JsonView value={rest} className="json-small" />}
            </li>
          );
        })}
      </ol>
    </div>
  );
}

function CypherView({ runs }: { runs: CypherRun[] }) {
  if (!runs.length) return <Empty>No Cypher queries were executed.</Empty>;
  return (
    <div className="cypher-list">
      {runs.map((c, i) => (
        <article key={i} className="cypher">
          <header className="row-between">
            <strong>{c.purpose}</strong>
            <span className="row-gap">
              <span className={`badge badge-${c.generated_by === 'llm' ? 'violet' : 'neutral'}`}>{c.generated_by}</span>
              <span className="muted small">{c.rows} rows</span>
            </span>
          </header>
          <pre className="code">{c.cypher.trim()}</pre>
          {c.params && Object.keys(c.params).length > 0 && (
            <details>
              <summary className="small">Parameters</summary>
              <JsonView value={c.params} className="json-small" />
            </details>
          )}
        </article>
      ))}
    </div>
  );
}
