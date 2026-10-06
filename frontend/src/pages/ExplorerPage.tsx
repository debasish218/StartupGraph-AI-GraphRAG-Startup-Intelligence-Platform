import { useCallback, useEffect, useRef, useState } from 'react';
import { api, errorMessage, type EntityHit, type Graph, type GraphNode } from '../api';
import { EntityMultiPicker, EntityPicker } from '../components/EntityPicker';
import { GraphView, mergeGraphs } from '../components/GraphView';
import { PathsList } from '../components/PathsList';
import { Card, ErrorBox, Loading } from '../components/Status';

type Mode = 'neighborhood' | 'relationship';

export function ExplorerPage() {
  const [mode, setMode] = useState<Mode>('neighborhood');

  // Neighbourhood mode
  const [focus, setFocus] = useState<{ id: string; name: string }>({ id: 'openai', name: 'OpenAI' });
  const [twoHop, setTwoHop] = useState(false);
  const [perNode, setPerNode] = useState(30);
  const [graph, setGraph] = useState<Graph | null>(null);
  const [loading, setLoading] = useState(false);
  const [expanding, setExpanding] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const reqSeq = useRef(0);

  const loadFocus = useCallback(async () => {
    const seq = ++reqSeq.current;
    setLoading(true);
    setError(null);
    try {
      const g = await api.neighborhood(focus.id, perNode, twoHop);
      if (seq !== reqSeq.current) return;
      setGraph(g);
    } catch (e) {
      if (seq === reqSeq.current) setError(errorMessage(e));
    } finally {
      if (seq === reqSeq.current) setLoading(false);
    }
  }, [focus.id, perNode, twoHop]);

  useEffect(() => {
    if (mode === 'neighborhood') void loadFocus();
  }, [loadFocus, mode]);

  const expand = useCallback(
    async (node: GraphNode) => {
      if (expanding) return;
      setExpanding(node.id);
      setError(null);
      try {
        const g = await api.neighborhood(node.id, perNode);
        setGraph((cur) => (cur ? mergeGraphs(cur, g) : g));
      } catch (e) {
        setError(`Could not expand ${node.label}: ${errorMessage(e)}`);
      } finally {
        setExpanding(null);
      }
    },
    [expanding, perNode],
  );

  // Relationship mode
  const [picked, setPicked] = useState<EntityHit[]>([]);
  const [rel, setRel] = useState<{ graph: Graph; paths: string[] } | null>(null);
  const [relLoading, setRelLoading] = useState(false);
  const [relError, setRelError] = useState<string | null>(null);

  const findRelationships = async () => {
    if (picked.length < 2) return;
    setRelLoading(true);
    setRelError(null);
    try {
      setRel(await api.relationship(picked.map((p) => p.id)));
    } catch (e) {
      setRelError(errorMessage(e));
    } finally {
      setRelLoading(false);
    }
  };

  return (
    <div className="page">
      <header className="page-head row-between wrap">
        <div>
          <h1>Graph explorer</h1>
          <p className="muted">Browse the knowledge graph around any company, investor, founder or technology.</p>
        </div>
        <div className="segmented" role="radiogroup" aria-label="Explorer mode">
          <button type="button" role="radio" aria-checked={mode === 'neighborhood'} className={mode === 'neighborhood' ? 'active' : ''} onClick={() => setMode('neighborhood')}>
            Neighbourhood
          </button>
          <button type="button" role="radio" aria-checked={mode === 'relationship'} className={mode === 'relationship' ? 'active' : ''} onClick={() => setMode('relationship')}>
            Relationship mode
          </button>
        </div>
      </header>

      {mode === 'neighborhood' ? (
        <Card
          title={
            <>
              Neighbourhood of <span className="accent">{focus.name}</span>
            </>
          }
          actions={
            <div className="toolbar">
              <div className="toolbar-picker">
                <EntityPicker placeholder="Search entity to explore…" onSelect={(h) => setFocus({ id: h.id, name: h.name })} />
              </div>
              <label className="check small">
                <input type="checkbox" checked={twoHop} onChange={(e) => setTwoHop(e.target.checked)} /> 2-hop
              </label>
              <label className="small">
                Per node{' '}
                <select className="select select-small" value={perNode} onChange={(e) => setPerNode(Number(e.target.value))}>
                  {[10, 20, 30, 50, 100].map((n) => (
                    <option key={n} value={n}>
                      {n}
                    </option>
                  ))}
                </select>
              </label>
              <button type="button" className="btn btn-small" onClick={() => void loadFocus()} disabled={loading}>
                Reset
              </button>
            </div>
          }
        >
          <ErrorBox error={error} onRetry={error && !graph ? () => void loadFocus() : undefined} />
          {loading && !graph ? (
            <Loading label="Loading neighbourhood…" />
          ) : (
            <GraphView graph={graph} height="calc(100vh - 250px)" onExpand={(n) => void expand(n)} busy={loading || expanding !== null} />
          )}
          {expanding && <p className="muted small">Expanding {graph?.nodes.find((n) => n.id === expanding)?.label ?? expanding}…</p>}
        </Card>
      ) : (
        <Card title="Relationship between entities">
          <div className="rel-controls">
            <EntityMultiPicker value={picked} onChange={setPicked} max={5} placeholder="Add 2–5 entities…" />
            <button type="button" className="btn btn-primary" disabled={picked.length < 2 || relLoading} onClick={() => void findRelationships()}>
              {relLoading ? 'Searching…' : 'Find relationships'}
            </button>
          </div>
          {picked.length < 2 && <p className="muted small">Pick at least two entities (e.g. OpenAI, Anthropic, Microsoft, Google).</p>}
          <ErrorBox error={relError} onRetry={() => void findRelationships()} />
          {relLoading && <Loading label="Finding connecting paths…" />}
          {rel && !relLoading && (
            <div className="rel-result">
              <GraphView graph={rel.graph} height={540} emptyMessage="No connecting subgraph found." />
              <h3 className="section-title">Paths ({rel.paths.length})</h3>
              <PathsList paths={rel.paths} />
            </div>
          )}
        </Card>
      )}
    </div>
  );
}
