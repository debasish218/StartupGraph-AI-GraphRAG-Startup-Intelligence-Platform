import { memo, useCallback, useEffect, useMemo, useRef, useState, type CSSProperties } from 'react';
import {
  Background,
  BaseEdge,
  Controls,
  Handle,
  MarkerType,
  MiniMap,
  Panel,
  Position,
  ReactFlow,
  ReactFlowProvider,
  useEdgesState,
  useNodesState,
  useReactFlow,
  type Edge,
  type EdgeProps,
  type Node,
  type NodeProps,
} from '@xyflow/react';
import '@xyflow/react/dist/style.css';
import {
  forceCollide,
  forceLink,
  forceManyBody,
  forceSimulation,
  forceX,
  forceY,
  type SimulationLinkDatum,
  type SimulationNodeDatum,
} from 'd3-force';
import type { Graph, GraphNode } from '../api';
import { edgeStyle, typeColor } from './graphStyle';
import { formatValue, humanize } from '../format';

type EntityData = { gnode: GraphNode; color: string };
type EntityNode = Node<EntityData, 'entity'>;

type Pos = { x: number; y: number };
type SimNode = SimulationNodeDatum & { id: string };

const NODE_W = 150;
const NODE_H = 40;

/** Force-directed layout (d3-force), run synchronously. Nodes found in `prev` are pinned. */
function computeLayout(graph: Graph, prev: Map<string, Pos>): Map<string, Pos> {
  const known = graph.nodes.filter((n) => prev.has(n.id)).length;
  const pinExisting = known > 0 && known >= graph.nodes.length * 0.3;
  const byId = new Map<string, SimNode>();
  const simNodes: SimNode[] = graph.nodes.map((n) => {
    const p = pinExisting ? prev.get(n.id) : undefined;
    const sn: SimNode = p ? { id: n.id, x: p.x, y: p.y, fx: p.x, fy: p.y } : { id: n.id };
    byId.set(n.id, sn);
    return sn;
  });
  const links: SimulationLinkDatum<SimNode>[] = graph.edges
    .filter((e) => byId.has(e.source) && byId.has(e.target) && e.source !== e.target)
    .map((e) => ({ source: e.source, target: e.target }));

  // Seed new nodes next to an already-placed neighbour so expansions grow outward.
  if (pinExisting) {
    for (const l of links) {
      const s = byId.get(l.source as string)!;
      const t = byId.get(l.target as string)!;
      const [placed, fresh] = s.fx !== undefined && t.x === undefined ? [s, t] : t.fx !== undefined && s.x === undefined ? [t, s] : [null, null];
      if (placed && fresh) {
        const a = Math.random() * Math.PI * 2;
        fresh.x = (placed.x ?? 0) + Math.cos(a) * 120;
        fresh.y = (placed.y ?? 0) + Math.sin(a) * 120;
      }
    }
  }

  const n = simNodes.length;
  const sim = forceSimulation<SimNode>(simNodes)
    .force(
      'link',
      forceLink<SimNode, SimulationLinkDatum<SimNode>>(links)
        .id((d) => d.id)
        .distance(n > 60 ? 130 : n < 10 ? 300 : 170)
        .strength(0.4),
    )
    .force('charge', forceManyBody<SimNode>().strength(n > 80 ? -500 : -800).distanceMax(900))
    .force('collide', forceCollide<SimNode>(NODE_W * 0.6))
    .force('x', forceX<SimNode>(0).strength(0.05))
    .force('y', forceY<SimNode>(0).strength(0.07))
    .stop();
  for (let i = 0; i < 300; i++) sim.tick();

  const out = new Map<string, Pos>();
  for (const sn of simNodes) out.set(sn.id, { x: (sn.x ?? 0) - NODE_W / 2, y: (sn.y ?? 0) - NODE_H / 2 });
  return out;
}

const centerHandle: CSSProperties = {
  top: '50%',
  left: '50%',
  transform: 'translate(-50%, -50%)',
  opacity: 0,
  width: 1,
  height: 1,
  minWidth: 0,
  minHeight: 0,
  border: 'none',
  pointerEvents: 'none',
};

const EntityNodeView = memo(function EntityNodeView({ data, selected }: NodeProps<EntityNode>) {
  const { gnode, color } = data;
  return (
    <div className={`gnode ${selected ? 'gnode-selected' : ''}`} style={{ borderColor: color }} title={`${gnode.label} (${gnode.type})`}>
      <Handle type="target" position={Position.Top} style={centerHandle} isConnectable={false} />
      <span className="gnode-dot" style={{ background: color }} />
      <span className="gnode-text">
        <span className="gnode-label">{gnode.label}</span>
        <span className="gnode-type">{gnode.type}</span>
      </span>
      <Handle type="source" position={Position.Bottom} style={centerHandle} isConnectable={false} />
    </div>
  );
});

const nodeTypes = { entity: EntityNodeView };

type RelEdge = Edge<{ offset: number; properties: Record<string, unknown> }, 'rel'>;

/** Clip a point at the border of a node box centred on (x, y), coming from direction (fx, fy). */
function clipToBox(x: number, y: number, fx: number, fy: number): [number, number] {
  const dx = x - fx;
  const dy = y - fy;
  if (dx === 0 && dy === 0) return [x, y];
  const hw = NODE_W / 2 + 3;
  const hh = NODE_H / 2 + 3;
  const t = Math.min(dx !== 0 ? hw / Math.abs(dx) : Infinity, dy !== 0 ? hh / Math.abs(dy) : Infinity);
  return t >= 1 ? [x, y] : [x - dx * t, y - dy * t];
}

/** Straight or gently curved edge (curved when several relationships join the same pair), clipped to node borders. */
function RelEdgeView({ id, sourceX, sourceY, targetX, targetY, data, label, labelStyle, labelBgStyle, labelBgPadding, labelBgBorderRadius, style, markerEnd }: EdgeProps<RelEdge>) {
  const off = data?.offset ?? 0;
  const dx = targetX - sourceX;
  const dy = targetY - sourceY;
  const len = Math.hypot(dx, dy) || 1;
  const nx = -dy / len;
  const ny = dx / len;
  const mx = (sourceX + targetX) / 2;
  const my = (sourceY + targetY) / 2;
  const cx = mx + nx * off * 2;
  const cy = my + ny * off * 2;
  const [sx, sy] = clipToBox(sourceX, sourceY, cx, cy);
  const [tx, ty] = clipToBox(targetX, targetY, cx, cy);
  const path = off === 0 ? `M ${sx},${sy} L ${tx},${ty}` : `M ${sx},${sy} Q ${cx},${cy} ${tx},${ty}`;
  const lx = 0.25 * sx + 0.5 * cx + 0.25 * tx;
  const ly = 0.25 * sy + 0.5 * cy + 0.25 * ty;
  return (
    <BaseEdge
      id={id}
      path={path}
      style={style}
      markerEnd={markerEnd}
      label={label}
      labelX={off === 0 ? (sx + tx) / 2 : lx}
      labelY={off === 0 ? (sy + ty) / 2 : ly}
      labelStyle={labelStyle}
      labelShowBg
      labelBgStyle={labelBgStyle}
      labelBgPadding={labelBgPadding}
      labelBgBorderRadius={labelBgBorderRadius}
    />
  );
}

const edgeTypes = { rel: RelEdgeView };

interface GraphViewProps {
  graph: Graph | null | undefined;
  height?: number | string;
  /** Called on node double-click (e.g. expand neighbourhood). */
  onExpand?: (node: GraphNode) => void;
  busy?: boolean;
  emptyMessage?: string;
}

export function GraphView(props: GraphViewProps) {
  return (
    <ReactFlowProvider>
      <GraphViewInner {...props} />
    </ReactFlowProvider>
  );
}

function GraphViewInner({ graph, height = 560, onExpand, busy, emptyMessage = 'No graph data for this result.' }: GraphViewProps) {
  const [nodes, setNodes, onNodesChange] = useNodesState<EntityNode>([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState<RelEdge>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [showLabels, setShowLabels] = useState(true);
  const positions = useRef(new Map<string, Pos>());
  const { fitView } = useReactFlow();

  const nodeById = useMemo(() => new Map((graph?.nodes ?? []).map((n) => [n.id, n])), [graph]);

  useEffect(() => {
    if (!graph) {
      setNodes([]);
      setEdges([]);
      return;
    }
    const pos = computeLayout(graph, positions.current);
    positions.current = pos;
    setNodes(
      graph.nodes.map((n) => ({
        id: n.id,
        type: 'entity',
        position: pos.get(n.id) ?? { x: 0, y: 0 },
        data: { gnode: n, color: typeColor(n.type) },
      })),
    );
    setSelectedId((cur) => (cur && graph.nodes.some((n) => n.id === cur) ? cur : null));
    const t = window.setTimeout(() => fitView({ padding: 0.15, duration: 300, maxZoom: 1.2 }), 60);
    return () => window.clearTimeout(t);
  }, [graph, setNodes, setEdges, fitView]);

  useEffect(() => {
    if (!graph) return;
    const ids = new Set(graph.nodes.map((n) => n.id));
    const pairCount = new Map<string, number>();
    setEdges(
      graph.edges
        .filter((e) => ids.has(e.source) && ids.has(e.target))
        .map((e) => {
          // Parallel edges between the same pair: first is straight, the rest curve so both stay visible.
          const forward = e.source < e.target;
          const pair = forward ? `${e.source}|${e.target}` : `${e.target}|${e.source}`;
          const nth = pairCount.get(pair) ?? 0;
          pairCount.set(pair, nth + 1);
          // 0, +28, -28, +56, -56 … ; sign flipped for reversed edges so offsets are consistent per pair.
          const magnitude = Math.ceil(nth / 2) * 28;
          const offset = (nth % 2 === 1 ? 1 : -1) * magnitude * (forward ? 1 : -1);
          const st = edgeStyle(e.type);
          const touchesSelected = selectedId !== null && (e.source === selectedId || e.target === selectedId);
          return {
            id: e.id,
            source: e.source,
            target: e.target,
            type: 'rel',
            label: showLabels || touchesSelected ? e.type : undefined,
            labelStyle: { fill: st.color, fontSize: 10, fontWeight: 600 },
            labelBgStyle: { fill: 'var(--surface)', fillOpacity: 0.9 },
            labelBgPadding: [4, 2] as [number, number],
            labelBgBorderRadius: 4,
            style: {
              stroke: st.color,
              strokeWidth: touchesSelected ? 2.5 : 1.5,
              strokeDasharray: st.dash,
              opacity: selectedId && !touchesSelected ? 0.35 : 1,
            },
            markerEnd: { type: MarkerType.ArrowClosed, color: st.color, width: 16, height: 16 },
            data: { offset, properties: e.properties },
          } satisfies RelEdge;
        }),
    );
  }, [graph, showLabels, selectedId, setEdges]);

  const presentTypes = useMemo(() => Array.from(new Set((graph?.nodes ?? []).map((n) => n.type))).sort(), [graph]);
  const presentEdges = useMemo(() => Array.from(new Set((graph?.edges ?? []).map((e) => e.type))).sort(), [graph]);

  const onNodeDragStop = useCallback((_: unknown, node: EntityNode) => {
    positions.current.set(node.id, node.position);
  }, []);

  const selected = selectedId ? nodeById.get(selectedId) ?? null : null;

  if (!graph || graph.nodes.length === 0) {
    return (
      <div className="graph-empty" style={{ height: typeof height === 'number' ? Math.min(height, 240) : 240 }}>
        {busy ? 'Loading graph…' : emptyMessage}
      </div>
    );
  }

  return (
    <div className={`graph-layout ${selected ? 'with-panel' : ''}`}>
      <div className="graph-wrap" style={{ height }}>
        <ReactFlow
          nodes={nodes}
          edges={edges}
          nodeTypes={nodeTypes}
          edgeTypes={edgeTypes}
          onNodesChange={onNodesChange}
          onEdgesChange={onEdgesChange}
          onNodeClick={(_, n) => setSelectedId(n.id)}
          onNodeDoubleClick={(_, n) => onExpand?.(n.data.gnode)}
          onNodeDragStop={onNodeDragStop}
          onPaneClick={() => setSelectedId(null)}
          nodesConnectable={false}
          zoomOnDoubleClick={!onExpand}
          minZoom={0.1}
          maxZoom={2.5}
          fitView
          fitViewOptions={{ padding: 0.15, maxZoom: 1.2 }}
          colorMode="system"
          proOptions={{ hideAttribution: true }}
        >
          <Background gap={20} size={1} />
          <Controls showInteractive={false} />
          <MiniMap pannable zoomable nodeColor={(n) => (n as EntityNode).data.color} nodeStrokeWidth={2} />
          <Panel position="top-left" className="graph-legend">
            <div className="legend-title">Nodes</div>
            {presentTypes.map((t) => (
              <div key={t} className="legend-item">
                <span className="legend-dot" style={{ background: typeColor(t) }} />
                {t}
              </div>
            ))}
            {presentEdges.length > 0 && <div className="legend-title">Edges</div>}
            {presentEdges.map((t) => {
              const st = edgeStyle(t);
              return (
                <div key={t} className="legend-item">
                  <svg width="22" height="8" aria-hidden="true">
                    <line x1="1" y1="4" x2="21" y2="4" stroke={st.color} strokeWidth="2" strokeDasharray={st.dash} />
                  </svg>
                  {t}
                </div>
              );
            })}
          </Panel>
          <Panel position="top-right" className="graph-toolbar">
            <span className="muted small">
              {graph.nodes.length} nodes · {graph.edges.length} edges
            </span>
            <label className="check small">
              <input type="checkbox" checked={showLabels} onChange={(e) => setShowLabels(e.target.checked)} /> Edge labels
            </label>
            {onExpand && <span className="muted small">Double-click a node to expand</span>}
            {busy && <span className="spinner spinner-small" aria-label="Loading" />}
          </Panel>
        </ReactFlow>
      </div>
      {selected && <NodePanel node={selected} graph={graph} onClose={() => setSelectedId(null)} onExpand={onExpand} onSelect={setSelectedId} />}
    </div>
  );
}

function NodePanel({
  node,
  graph,
  onClose,
  onExpand,
  onSelect,
}: {
  node: GraphNode;
  graph: Graph;
  onClose: () => void;
  onExpand?: (n: GraphNode) => void;
  onSelect: (id: string) => void;
}) {
  const names = useMemo(() => new Map(graph.nodes.map((n) => [n.id, n.label])), [graph]);
  const rels = graph.edges.filter((e) => e.source === node.id || e.target === node.id);
  const props = Object.entries(node.properties ?? {}).filter(([, v]) => v !== null && v !== undefined && v !== '');
  return (
    <aside className="node-panel">
      <header className="node-panel-head">
        <span className="legend-dot" style={{ background: typeColor(node.type) }} />
        <div className="node-panel-title">
          <strong>{node.label}</strong>
          <span className="muted small">{node.labels.join(' · ') || node.type}</span>
        </div>
        <button type="button" className="icon-btn" onClick={onClose} aria-label="Close panel">
          ×
        </button>
      </header>
      {onExpand && (
        <button type="button" className="btn btn-small" onClick={() => onExpand(node)}>
          Expand neighbourhood
        </button>
      )}
      <h4>Properties</h4>
      {props.length === 0 ? (
        <p className="muted small">No properties.</p>
      ) : (
        <dl className="props">
          {props.map(([k, v]) => (
            <div key={k} className="prop-row">
              <dt>{humanize(k)}</dt>
              <dd>
                {typeof v === 'string' && /^https?:\/\//.test(v) ? (
                  <a href={v} target="_blank" rel="noreferrer">
                    {v}
                  </a>
                ) : (
                  formatValue(v, k)
                )}
              </dd>
            </div>
          ))}
        </dl>
      )}
      <h4>Relationships ({rels.length})</h4>
      <ul className="rel-list">
        {rels.slice(0, 60).map((e) => {
          const out = e.source === node.id;
          const other = out ? e.target : e.source;
          return (
            <li key={e.id}>
              <span className="rel-type" style={{ color: edgeStyle(e.type).color }}>
                {out ? '→' : '←'} {e.type}
              </span>{' '}
              <button type="button" className="link-btn" onClick={() => onSelect(other)}>
                {names.get(other) ?? other}
              </button>
            </li>
          );
        })}
      </ul>
    </aside>
  );
}

/** Merge two graphs, de-duplicating nodes and edges by id. */
export function mergeGraphs(a: Graph, b: Graph): Graph {
  const nodes = new Map(a.nodes.map((n) => [n.id, n]));
  for (const n of b.nodes) if (!nodes.has(n.id)) nodes.set(n.id, n);
  const edges = new Map(a.edges.map((e) => [e.id, e]));
  for (const e of b.edges) if (!edges.has(e.id)) edges.set(e.id, e);
  return { nodes: [...nodes.values()], edges: [...edges.values()] };
}
