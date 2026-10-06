import ReactMarkdown, { type Components } from 'react-markdown';

const CITE_PREFIX = '#cite-';

/** Turn citation markers like [D1], [G], [D2, D3] into links the renderer can style. */
export function linkifyCitations(md: string): string {
  return md.replace(/\[((?:G|D\d+)(?:\s*,\s*(?:G|D\d+))*)\](?!\()/g, (_m, inner: string) =>
    inner
      .split(',')
      .map((s) => s.trim())
      .map((id) => `[${id}](${CITE_PREFIX}${id})`)
      .join(''),
  );
}

const LIST_ITEM = /^\s*(?:[-*+]|\d+[.)])\s/;

/**
 * Answers use single newlines as line breaks. Keep them visible: a plain line after a list item
 * starts a new paragraph (instead of folding into the item), and consecutive plain lines get hard breaks.
 */
export function normalizeLineBreaks(md: string): string {
  const lines = md.split('\n');
  const out: string[] = [];
  let inFence = false;
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    if (/^\s*(```|~~~)/.test(line)) inFence = !inFence;
    if (inFence) {
      out.push(line);
      continue;
    }
    const prev = i > 0 ? lines[i - 1] : '';
    const next = i + 1 < lines.length ? lines[i + 1] : '';
    const plain = (l: string) => l.trim() !== '' && !/^\s/.test(l) && !LIST_ITEM.test(l) && !/^(#|>|\||```)/.test(l);
    if (i > 0 && plain(line) && LIST_ITEM.test(prev)) out.push('');
    out.push(plain(line) && next.trim() !== '' && !LIST_ITEM.test(next) && plain(next) ? `${line}  ` : line);
  }
  return out.join('\n');
}

export function Markdown({ text, onCite }: { text: string; onCite?: (id: string) => void }) {
  const components: Components = {
    a: ({ href, children }) => {
      if (href && href.startsWith(CITE_PREFIX)) {
        const id = href.slice(CITE_PREFIX.length);
        return (
          <button
            type="button"
            className={`cite ${id === 'G' ? 'cite-graph' : 'cite-doc'}`}
            title={id === 'G' ? 'Knowledge graph evidence' : `Document ${id}`}
            onClick={() => onCite?.(id)}
          >
            {children}
          </button>
        );
      }
      return (
        <a href={href} target="_blank" rel="noreferrer">
          {children}
        </a>
      );
    },
  };
  return (
    <div className="markdown">
      <ReactMarkdown components={components}>{linkifyCitations(normalizeLineBreaks(text))}</ReactMarkdown>
    </div>
  );
}
