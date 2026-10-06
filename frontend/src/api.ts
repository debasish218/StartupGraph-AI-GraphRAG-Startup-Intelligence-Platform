// API types and fetch helpers for the StartupGraph AI backend.

export type NodeType =
  | 'Company'
  | 'Investor'
  | 'Founder'
  | 'Technology'
  | 'FundingRound'
  | 'NewsArticle'
  | string;

export type Props = Record<string, unknown>;

export interface GraphNode {
  id: string;
  label: string;
  type: NodeType;
  labels: string[];
  properties: Props;
}

export interface GraphEdge {
  id: string;
  source: string;
  target: string;
  type: string;
  properties: Props;
}

export interface Graph {
  nodes: GraphNode[];
  edges: GraphEdge[];
}

export interface EntityRef {
  id: string;
  name: string;
  type?: string;
}

export interface QueryEntities {
  companies: EntityRef[];
  investors: EntityRef[];
  founders: EntityRef[];
  technologies: EntityRef[];
  employers: EntityRef[];
  topics: string[];
  round_types: string[];
  date_from: string | null;
  date_to: string | null;
  date_strict: boolean;
  limit: number | null;
}

export interface ConfidenceComponents {
  classification: number;
  entity_resolution: number;
  graph_evidence: number;
  document_evidence: number;
  [k: string]: number;
}

export interface Confidence {
  score: number;
  level: 'high' | 'medium' | 'low';
  components: ConfidenceComponents;
}

export interface Source {
  id: string;
  type: string;
  title: string;
  url?: string | null;
  published_at?: string | null;
  score?: number | null;
  source?: string | null;
  detail?: string[] | null;
}

export interface CypherRun {
  purpose: string;
  cypher: string;
  params: Props;
  rows: number;
  generated_by: 'template' | 'llm' | string;
}

export interface DocumentHit {
  title: string;
  doc_type: string;
  snippet: string;
  score: number;
  url: string | null;
  published_at: string | null;
  source: string | null;
  company_ids: string[];
}

export interface Ranking {
  company_id: string;
  name: string;
  funding: number;
  news: number;
  hiring: number;
  investor_quality: number;
  score: number;
  total_funding: number | null;
  employee_growth_pct: number | null;
  news_articles: number | null;
  investors: string[];
  sector: string | null;
}

export interface SimilarCompany {
  id: string;
  name: string;
  sector: string | null;
  score: number;
  components: { embedding: number; technology: number; investor: number; sector: number };
  shared_technologies: string[];
  shared_investors: string[];
  investors: string[];
  total_funding: number | null;
}

export interface TraceEntry {
  agent: string;
  ms: number;
  [k: string]: unknown;
}

export interface QueryResponse {
  question: string;
  answer: string;
  answer_mode: 'llm' | 'template' | string;
  query_type: 'graph' | 'vector' | 'hybrid' | string;
  intent: string;
  classification_reason: string;
  entities: QueryEntities;
  confidence: Confidence;
  sources: Source[];
  paths: string[];
  cypher: CypherRun[];
  graph: Graph;
  documents: DocumentHit[];
  rankings: Ranking[];
  similar: SimilarCompany[];
  notes: string[];
  errors: string[];
  trace: TraceEntry[];
  latency_ms: number;
}

export interface EntityHit {
  id: string;
  name: string;
  labels: string[];
}

export interface RelationshipResponse {
  graph: Graph;
  paths: string[];
}

export interface CompanySummary {
  id: string;
  name: string;
  sector: string | null;
  country: string | null;
  founded_year: number | null;
  employees: number | null;
  total_funding: number | null;
  employee_growth_pct: number | null;
}

export interface FundingRoundInfo {
  round: string | null;
  amount: number | null;
  date: string | null;
}

export interface CompanyProfile {
  id: string;
  name: string;
  description: string | null;
  sector: string | null;
  country: string | null;
  founded_year: number | null;
  employees: number | null;
  employee_growth_pct: number | null;
  total_funding: number | null;
  website: string | null;
  founders: string[];
  investors: string[];
  lead_investors: string[];
  technologies: string[];
  competitors: string[];
  partners: string[];
  acquisitions: string[];
  acquired_by: string[];
  funding_rounds: FundingRoundInfo[];
}

export interface NewsItem {
  title: string;
  published_at: string | null;
  url: string | null;
  sentiment: number | string | null;
  snippet: string | null;
}

export interface CompanyDetail {
  profile: CompanyProfile;
  score: Ranking | null;
  news: NewsItem[];
}

export interface RankingWeights {
  funding: number;
  news: number;
  hiring: number;
  investor_quality: number;
}

export interface RankingsResponse {
  weights: RankingWeights;
  topic: string | null;
  rankings: Ranking[];
}

export interface Recommendation extends Ranking {
  growth_score: number;
  similar_companies: { id: string; name: string; score: number }[];
}

export interface InvestorDiscovery {
  id: string;
  investor: string;
  type: string | null;
  quality: number | null;
  startups_backed: number;
  rounds: number;
  rounds_led: number;
  round_volume: number | null;
  portfolio: string[];
  sectors: string[];
}

export interface CompareResponse {
  companies: (CompanyProfile & { score: Ranking | null })[];
  in_common: { investors: string[]; technologies: string[]; competitors: string[]; partners: string[] };
}

export interface TrendRow {
  year: number;
  sector: string | null;
  rounds: number;
  amount: number | null;
}

export interface SectorRow {
  sector: string | null;
  companies: number;
  total_funding: number | null;
  avg_hiring_growth: number | null;
}

export interface Stats {
  graph: Record<string, number>;
  documents: Record<string, number>;
  llm_provider: string;
  embedding_model: string;
}

export interface DetectedEvent {
  type: string;
  company: string | null;
  counterparty: string | null;
  amount: number | null;
  round_type: string | null;
  lead_investors: string[] | null;
  investors: string[] | null;
  product: string | null;
  evidence: string | null;
}

export interface IngestArticleResponse {
  status: string;
  title?: string;
  events?: DetectedEvent[];
  graph_updates?: Props[];
  mentions?: string[];
  sentiment?: number | string | null;
}

export interface IngestRssResponse {
  ingested: number;
  duplicates: number;
  errors: number | string[];
  graph_updates: number | Props[];
  items: Props[];
}

export interface IngestYcResponse {
  imported: number;
  documents_added: number;
}

export interface IngestGithubResponse {
  updated: number;
  errors: string[];
}

// ---------------------------------------------------------------- helpers

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
    this.name = 'ApiError';
  }
}

const API_KEY_STORAGE = 'startupgraph.apiKey';

export function getApiKey(): string {
  try {
    return window.localStorage.getItem(API_KEY_STORAGE) ?? '';
  } catch {
    return '';
  }
}

export function setApiKey(key: string): void {
  try {
    if (key) window.localStorage.setItem(API_KEY_STORAGE, key);
    else window.localStorage.removeItem(API_KEY_STORAGE);
  } catch {
    /* storage unavailable: ignore */
  }
}

function detailToMessage(detail: unknown): string {
  if (typeof detail === 'string') return detail;
  if (Array.isArray(detail)) {
    return detail
      .map((d) => {
        if (d && typeof d === 'object' && 'msg' in d) {
          const loc = Array.isArray((d as { loc?: unknown[] }).loc)
            ? (d as { loc: unknown[] }).loc.join('.')
            : '';
          return `${loc ? loc + ': ' : ''}${String((d as { msg: unknown }).msg)}`;
        }
        return JSON.stringify(d);
      })
      .join('; ');
  }
  return JSON.stringify(detail);
}

type Query = Record<string, string | number | boolean | null | undefined>;

function buildUrl(path: string, query?: Query): string {
  if (!query) return path;
  const sp = new URLSearchParams();
  for (const [k, v] of Object.entries(query)) {
    if (v === undefined || v === null || v === '') continue;
    sp.set(k, String(v));
  }
  const qs = sp.toString();
  return qs ? `${path}?${qs}` : path;
}

interface RequestOpts {
  method?: 'GET' | 'POST';
  query?: Query;
  body?: unknown;
  auth?: boolean;
  signal?: AbortSignal;
}

export async function request<T>(path: string, opts: RequestOpts = {}): Promise<T> {
  const headers: Record<string, string> = { Accept: 'application/json' };
  if (opts.body !== undefined) headers['Content-Type'] = 'application/json';
  if (opts.auth) {
    const key = getApiKey();
    if (key) headers['X-API-Key'] = key;
  }
  let res: Response;
  try {
    res = await fetch(buildUrl(path, opts.query), {
      method: opts.method ?? 'GET',
      headers,
      body: opts.body !== undefined ? JSON.stringify(opts.body) : undefined,
      signal: opts.signal,
    });
  } catch (e) {
    if (e instanceof DOMException && e.name === 'AbortError') throw e;
    throw new ApiError(0, 'Network error: could not reach the API server.');
  }
  const text = await res.text();
  let data: unknown = null;
  if (text) {
    try {
      data = JSON.parse(text);
    } catch {
      data = text;
    }
  }
  if (!res.ok) {
    let msg = `HTTP ${res.status}`;
    if (data && typeof data === 'object' && 'detail' in data) {
      msg = `${msg}: ${detailToMessage((data as { detail: unknown }).detail)}`;
    } else if (typeof data === 'string' && data.length < 300) {
      msg = `${msg}: ${data}`;
    }
    throw new ApiError(res.status, msg);
  }
  return data as T;
}

export const api = {
  health: (signal?: AbortSignal) => request<{ status: string }>('/health', { signal }),
  query: (question: string, signal?: AbortSignal) =>
    request<QueryResponse>('/api/query', { method: 'POST', body: { question }, signal }),
  searchEntities: (q: string, limit = 10, signal?: AbortSignal) =>
    request<EntityHit[]>('/api/entities/search', { query: { q, limit }, signal }),
  neighborhood: (id: string, perNode = 30, expand?: boolean) =>
    request<Graph>('/api/graph/neighborhood', { query: { id, per_node: perNode, expand } }),
  relationship: (ids: string[]) =>
    request<RelationshipResponse>('/api/graph/relationship', { query: { ids: ids.join(',') } }),
  companies: (q?: string, sector?: string, limit = 50) =>
    request<CompanySummary[]>('/api/companies', { query: { q, sector, limit } }),
  company: (id: string) => request<CompanyDetail>(`/api/companies/${encodeURIComponent(id)}`),
  similar: (id: string, differentInvestors: boolean, limit = 10) =>
    request<SimilarCompany[]>(`/api/companies/${encodeURIComponent(id)}/similar`, {
      query: { different_investors: differentInvestors, limit },
    }),
  topics: () => request<string[]>('/api/topics'),
  rankings: (topic: string, limit = 25) =>
    request<RankingsResponse>('/api/rankings', { query: { topic, limit } }),
  recommendations: (topic: string, limit = 10) =>
    request<Recommendation[]>('/api/recommendations', { query: { topic, limit } }),
  discoverInvestors: (topic: string, limit = 25) =>
    request<InvestorDiscovery[]>('/api/investors/discover', { query: { topic, limit } }),
  compare: (ids: string[]) => request<CompareResponse>('/api/compare', { query: { ids: ids.join(',') } }),
  trends: (topic: string) => request<TrendRow[]>('/api/analytics/trends', { query: { topic } }),
  sectors: () => request<SectorRow[]>('/api/analytics/sectors'),
  stats: () => request<Stats>('/api/stats'),
  ingestArticle: (body: { title: string; body: string; url?: string; published_at?: string }) =>
    request<IngestArticleResponse>('/api/ingest/article', { method: 'POST', body, auth: true }),
  ingestRss: (maxItems = 20, feeds?: string[]) =>
    request<IngestRssResponse>('/api/ingest/rss', {
      method: 'POST',
      body: feeds && feeds.length ? { feeds, max_items: maxItems } : { max_items: maxItems },
      auth: true,
    }),
  ingestYc: (body: { industry?: string; tag?: string; batch?: string; limit: number }) =>
    request<IngestYcResponse>('/api/ingest/yc', { method: 'POST', body, auth: true }),
  ingestGithub: () => request<IngestGithubResponse>('/api/ingest/github', { method: 'POST', auth: true }),
};

export function errorMessage(e: unknown): string {
  if (e instanceof Error) return e.message;
  return String(e);
}
