export const NODE_TYPES = ['Company', 'Investor', 'Founder', 'Technology', 'FundingRound', 'NewsArticle'] as const;

const TYPE_COLORS: Record<string, string> = {
  Company: '#2a78d6',
  Investor: '#1baf7a',
  Founder: '#9b59d0',
  Technology: '#eda100',
  FundingRound: '#eb6834',
  NewsArticle: '#7d8590',
};

export function typeColor(type: string | undefined): string {
  return (type && TYPE_COLORS[type]) || '#8a8f98';
}

export interface EdgeStyle {
  color: string;
  dash?: string;
}

const EDGE_STYLES: Record<string, EdgeStyle> = {
  FOUNDED_BY: { color: '#9b59d0' },
  INVESTED_BY: { color: '#1f9d55' },
  RAISED: { color: '#eb6834' },
  USES_TECH: { color: '#c98500' },
  COMPETES_WITH: { color: '#e34948', dash: '6 4' },
  PARTNERS_WITH: { color: '#2a78d6' },
  ACQUIRED: { color: '#b4387a' },
  WORKED_AT: { color: '#64748b', dash: '2 3' },
  MENTIONED_IN: { color: '#9aa0a6', dash: '1 4' },
};

export function edgeStyle(type: string): EdgeStyle {
  return EDGE_STYLES[type] ?? { color: '#9aa0a6' };
}

export const EDGE_TYPES = Object.keys(EDGE_STYLES);
