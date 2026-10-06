import { useTopics } from '../hooks';

export function TopicSelect({ value, onChange, id, allLabel = 'All topics' }: { value: string; onChange: (v: string) => void; id?: string; allLabel?: string }) {
  const { data, loading, error } = useTopics();
  return (
    <select id={id} className="select" value={value} onChange={(e) => onChange(e.target.value)} disabled={loading} title={error ?? undefined}>
      <option value="">{loading ? 'Loading topics…' : error ? 'All (topics unavailable)' : allLabel}</option>
      {(data ?? []).map((t) => (
        <option key={t} value={t}>
          {t}
        </option>
      ))}
    </select>
  );
}
