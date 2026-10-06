import { useRef, useState, type FormEvent } from 'react';
import { api, errorMessage } from '../api';
import { AnswerPanel } from '../components/AnswerPanel';
import { ErrorBox, Loading } from '../components/Status';
import { useAskSession } from '../session';

export const EXAMPLES = [
  'Which startups compete with OpenAI?',
  'Which investors actively fund AI startups?',
  'Show AI startups founded by ex-Google employees.',
  'Which startups are similar to Anthropic but funded by different investors?',
  'Which companies raised Series B after 2024 and operate in Computer Vision?',
  'Show the relationship between OpenAI, Anthropic, Microsoft, and Google.',
  'Find promising Computer Vision startups.',
  'Compare OpenAI and Anthropic',
  'What is Perplexity?',
];

let nextId = 1;

export function AskPage() {
  const { history, setHistory, currentId, setCurrentId, pendingId, setPendingId } = useAskSession();
  const [question, setQuestion] = useState('');
  const abortRef = useRef<AbortController | null>(null);

  const current = history.find((h) => h.id === currentId) ?? null;

  const ask = async (q: string) => {
    const text = q.trim();
    if (!text || pendingId !== null) return;
    const id = nextId++;
    abortRef.current?.abort();
    const ctrl = new AbortController();
    abortRef.current = ctrl;
    setHistory((h) => [{ id, question: text, at: new Date(), response: null, error: null }, ...h]);
    setCurrentId(id);
    setPendingId(id);
    try {
      const res = await api.query(text, ctrl.signal);
      setHistory((h) => h.map((x) => (x.id === id ? { ...x, response: res } : x)));
    } catch (e) {
      const msg = e instanceof DOMException && e.name === 'AbortError' ? 'Cancelled.' : errorMessage(e);
      setHistory((h) => h.map((x) => (x.id === id ? { ...x, error: msg } : x)));
    } finally {
      setPendingId(null);
    }
  };

  const onSubmit = (e: FormEvent) => {
    e.preventDefault();
    void ask(question);
  };

  return (
    <div className="page page-ask">
      <div className="ask-main">
        <header className="page-head">
          <h1>Ask the startup graph</h1>
          <p className="muted">Questions are classified, routed to graph, vector or hybrid retrieval, and answered with citations.</p>
        </header>
        <form className="ask-form" onSubmit={onSubmit}>
          <textarea
            className="input ask-input"
            value={question}
            rows={2}
            placeholder="e.g. Which investors actively fund AI startups?"
            onChange={(e) => setQuestion(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                void ask(question);
              }
            }}
          />
          <div className="ask-actions">
            {pendingId !== null ? (
              <button type="button" className="btn" onClick={() => abortRef.current?.abort()}>
                Cancel
              </button>
            ) : null}
            <button type="submit" className="btn btn-primary" disabled={!question.trim() || pendingId !== null}>
              {pendingId !== null ? 'Thinking…' : 'Ask'}
            </button>
          </div>
        </form>
        <div className="chips examples">
          {EXAMPLES.map((ex) => (
            <button
              key={ex}
              type="button"
              className="chip chip-btn"
              disabled={pendingId !== null}
              onClick={() => {
                setQuestion(ex);
                void ask(ex);
              }}
            >
              {ex}
            </button>
          ))}
        </div>

        {current && (
          <section className="card answer-card">
            <h2 className="answer-question">{current.question}</h2>
            {current.id === pendingId && <Loading label="Running agents: classify → resolve entities → retrieve → answer…" />}
            <ErrorBox error={current.error} onRetry={() => void ask(current.question)} />
            {current.response && <AnswerPanel response={current.response} />}
          </section>
        )}
        {!current && (
          <div className="empty hero-empty">
            Ask a question or pick an example above. Answers include the evidence subgraph, relationship paths, cited sources, rankings, the agent trace and the
            executed Cypher.
          </div>
        )}
      </div>
      <aside className={`history ${history.length === 0 ? 'history-empty' : ''}`}>
        <h3 className="section-title">Session history</h3>
        {history.length === 0 && <p className="muted small">No questions yet.</p>}
        <ul>
          {history.map((h) => (
            <li key={h.id}>
              <button type="button" className={`history-item ${h.id === currentId ? 'active' : ''}`} onClick={() => setCurrentId(h.id)}>
                <span className="history-q">{h.question}</span>
                <span className="muted small">
                  {h.at.toLocaleTimeString()} ·{' '}
                  {h.id === pendingId ? 'running…' : h.error ? 'error' : h.response ? `${h.response.query_type}, ${Math.round(h.response.latency_ms)} ms` : ''}
                </span>
              </button>
            </li>
          ))}
        </ul>
        {history.length > 0 && (
          <button type="button" className="btn btn-small" disabled={pendingId !== null} onClick={() => { setHistory([]); setCurrentId(null); }}>
            Clear history
          </button>
        )}
      </aside>
    </div>
  );
}
