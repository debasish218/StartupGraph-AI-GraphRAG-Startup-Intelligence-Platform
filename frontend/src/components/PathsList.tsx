import { edgeStyle } from './graphStyle';
import { Empty } from './Status';

const REL = /(<?-\[[A-Za-z_]+\]->?)/g;

export function PathView({ path }: { path: string }) {
  const parts = path.split(REL).filter((p) => p !== '');
  return (
    <span className="path">
      {parts.map((p, i) => {
        const m = p.match(/^(<?)-\[([A-Za-z_]+)\]-(>?)$/);
        if (m) {
          const st = edgeStyle(m[2]);
          return (
            <span key={i} className="path-rel" style={{ color: st.color, borderColor: st.color }}>
              {m[1] ? '←' : ''}
              {m[2]}
              {m[3] ? '→' : ''}
            </span>
          );
        }
        return (
          <span key={i} className="path-node">
            {p.trim()}
          </span>
        );
      })}
    </span>
  );
}

export function PathsList({ paths }: { paths: string[] }) {
  if (!paths.length) return <Empty>No relationship paths.</Empty>;
  return (
    <ol className="paths">
      {paths.map((p, i) => (
        <li key={`${i}-${p}`}>
          <PathView path={p} />
        </li>
      ))}
    </ol>
  );
}
