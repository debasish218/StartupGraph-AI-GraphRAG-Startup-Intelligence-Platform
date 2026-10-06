import { useEffect, useId, useRef, useState } from 'react';
import { api, errorMessage, type EntityHit } from '../api';
import { useDebounced } from '../hooks';
import { typeColor } from './graphStyle';

interface PickerProps {
  onSelect: (hit: EntityHit) => void;
  placeholder?: string;
  /** Only show entities carrying this label (e.g. "Company"). */
  label?: string;
  exclude?: string[];
  disabled?: boolean;
  autoFocus?: boolean;
}

/** Autocomplete input backed by GET /api/entities/search. */
export function EntityPicker({ onSelect, placeholder = 'Search entities…', label, exclude = [], disabled, autoFocus }: PickerProps) {
  const [q, setQ] = useState('');
  const [hits, setHits] = useState<EntityHit[]>([]);
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const debounced = useDebounced(q.trim(), 200);
  const listId = useId();
  const wrapRef = useRef<HTMLDivElement>(null);
  const excludeKey = exclude.join('|');

  useEffect(() => {
    if (!debounced) {
      setHits([]);
      setError(null);
      return;
    }
    const ctrl = new AbortController();
    setLoading(true);
    setError(null);
    api
      .searchEntities(debounced, label ? 25 : 10, ctrl.signal)
      .then((res) => {
        const ex = new Set(excludeKey ? excludeKey.split('|') : []);
        let list = res.filter((h) => !ex.has(h.id));
        if (label) list = list.filter((h) => h.labels.includes(label));
        setHits(list.slice(0, 10));
        setActive(0);
      })
      .catch((e: unknown) => {
        if (e instanceof DOMException && e.name === 'AbortError') return;
        setError(errorMessage(e));
        setHits([]);
      })
      .finally(() => {
        if (!ctrl.signal.aborted) setLoading(false);
      });
    return () => ctrl.abort();
  }, [debounced, label, excludeKey]);

  useEffect(() => {
    const onDoc = (e: MouseEvent) => {
      if (wrapRef.current && !wrapRef.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener('mousedown', onDoc);
    return () => document.removeEventListener('mousedown', onDoc);
  }, []);

  const choose = (h: EntityHit) => {
    onSelect(h);
    setQ('');
    setHits([]);
    setOpen(false);
  };

  const showList = open && q.trim().length > 0;

  return (
    <div className="picker" ref={wrapRef}>
      <input
        className="input"
        type="search"
        value={q}
        placeholder={placeholder}
        disabled={disabled}
        autoFocus={autoFocus}
        role="combobox"
        aria-expanded={showList}
        aria-controls={listId}
        aria-autocomplete="list"
        onChange={(e) => {
          setQ(e.target.value);
          setOpen(true);
        }}
        onFocus={() => setOpen(true)}
        onKeyDown={(e) => {
          if (e.key === 'ArrowDown') {
            e.preventDefault();
            setActive((a) => Math.min(a + 1, hits.length - 1));
          } else if (e.key === 'ArrowUp') {
            e.preventDefault();
            setActive((a) => Math.max(a - 1, 0));
          } else if (e.key === 'Enter') {
            e.preventDefault();
            if (hits[active]) choose(hits[active]);
          } else if (e.key === 'Escape') {
            setOpen(false);
          }
        }}
      />
      {showList && (
        <ul className="picker-list" id={listId} role="listbox">
          {loading && <li className="picker-msg">Searching…</li>}
          {!loading && error && <li className="picker-msg picker-err">{error}</li>}
          {!loading && !error && hits.length === 0 && debounced && <li className="picker-msg">No matches</li>}
          {!loading &&
            hits.map((h, i) => (
              <li
                key={h.id}
                role="option"
                aria-selected={i === active}
                className={`picker-item ${i === active ? 'active' : ''}`}
                onMouseEnter={() => setActive(i)}
                onMouseDown={(e) => {
                  e.preventDefault();
                  choose(h);
                }}
              >
                <span className="dot" style={{ background: typeColor(h.labels[0]) }} />
                <span className="picker-name">{h.name}</span>
                <span className="picker-labels">{h.labels.join(', ')}</span>
              </li>
            ))}
        </ul>
      )}
    </div>
  );
}

interface MultiProps {
  value: EntityHit[];
  onChange: (v: EntityHit[]) => void;
  max?: number;
  label?: string;
  placeholder?: string;
}

/** Multi-select variant rendering the selection as removable chips. */
export function EntityMultiPicker({ value, onChange, max = 5, label, placeholder }: MultiProps) {
  const full = value.length >= max;
  return (
    <div className="multipicker">
      <div className="chips">
        {value.map((v) => (
          <span key={v.id} className="chip chip-removable">
            <span className="dot" style={{ background: typeColor(v.labels[0]) }} />
            {v.name}
            <button type="button" aria-label={`Remove ${v.name}`} onClick={() => onChange(value.filter((x) => x.id !== v.id))}>
              ×
            </button>
          </span>
        ))}
      </div>
      <EntityPicker
        label={label}
        exclude={value.map((v) => v.id)}
        disabled={full}
        placeholder={full ? `Maximum ${max} selected` : placeholder ?? `Add entity (${value.length}/${max})…`}
        onSelect={(h) => onChange([...value, h])}
      />
    </div>
  );
}
