import { useState } from 'react';
import { api } from '../api';
import { FundingTrendsChart, SectorChart } from '../components/Charts';
import { CompanyDrawer } from '../components/CompanyDrawer';
import { RankingTable } from '../components/RankingTable';
import { ComponentLegend, DEFAULT_WEIGHTS, Formula } from '../components/ScoreBar';
import { Card, ErrorBox, Loading } from '../components/Status';
import { TopicSelect } from '../components/TopicSelect';
import { useAsync } from '../hooks';

export function RankingsPage() {
  const [topic, setTopic] = useState('');
  const [selected, setSelected] = useState<string | null>(null);
  const rankings = useAsync(() => api.rankings(topic, 25), [topic]);
  const trends = useAsync(() => api.trends(topic), [topic]);
  const sectors = useAsync(() => api.sectors(), []);
  const weights = rankings.data?.weights ?? DEFAULT_WEIGHTS;

  return (
    <div className="page">
      <header className="page-head row-between wrap">
        <div>
          <h1>Startup ranking dashboard</h1>
          <p className="muted">Composite score from funding, news sentiment, hiring growth and investor quality.</p>
        </div>
        <label className="field-inline">
          <span className="small muted">Topic</span>
          <TopicSelect value={topic} onChange={setTopic} allLabel="All" />
        </label>
      </header>

      <Card
        title={`Top startups${topic ? ` · ${topic}` : ''}`}
        actions={<Formula weights={weights} />}
      >
        <ComponentLegend />
        <ErrorBox error={rankings.error} onRetry={rankings.reload} />
        {rankings.loading ? <Loading /> : rankings.data && <RankingTable rankings={rankings.data.rankings} weights={weights} onSelect={(r) => setSelected(r.company_id)} />}
      </Card>

      <div className="grid-2">
        <Card title={`Funding by year${topic ? ` · ${topic}` : ''}`}>
          <ErrorBox error={trends.error} onRetry={trends.reload} />
          {trends.loading ? <Loading /> : trends.data && <FundingTrendsChart rows={trends.data} />}
        </Card>
        <Card title="Sector breakdown">
          <ErrorBox error={sectors.error} onRetry={sectors.reload} />
          {sectors.loading ? <Loading /> : sectors.data && <SectorChart rows={sectors.data} />}
        </Card>
      </div>

      <CompanyDrawer id={selected} onClose={() => setSelected(null)} />
    </div>
  );
}
