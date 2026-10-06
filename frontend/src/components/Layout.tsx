import { useEffect, useState } from 'react';
import { NavLink, Outlet, useLocation } from 'react-router-dom';
import { api } from '../api';

const NAV = [
  { to: '/', label: 'Ask', icon: '?' , end: true },
  { to: '/explorer', label: 'Explorer', icon: '◎' },
  { to: '/rankings', label: 'Rankings', icon: '▤' },
  { to: '/discover', label: 'Discover', icon: '✦' },
  { to: '/compare', label: 'Compare', icon: '⇄' },
  { to: '/ingest', label: 'Ingest', icon: '⇪' },
];

type Health = 'checking' | 'ok' | 'down';

function useHealth(): Health {
  const [h, setH] = useState<Health>('checking');
  useEffect(() => {
    let alive = true;
    const check = () =>
      api
        .health()
        .then((r) => alive && setH(r?.status === 'ok' ? 'ok' : 'down'))
        .catch(() => alive && setH('down'));
    check();
    const t = window.setInterval(check, 30000);
    return () => {
      alive = false;
      window.clearInterval(t);
    };
  }, []);
  return h;
}

export function Layout() {
  const health = useHealth();
  const [navOpen, setNavOpen] = useState(false);
  const loc = useLocation();
  useEffect(() => setNavOpen(false), [loc.pathname]);

  return (
    <div className={`app ${navOpen ? 'nav-open' : ''}`}>
      <header className="topbar">
        <button type="button" className="icon-btn nav-toggle" aria-label="Toggle navigation" onClick={() => setNavOpen((o) => !o)}>
          ☰
        </button>
        <div className="brand">
          <img src="/favicon.svg" alt="" width={24} height={24} />
          <span>StartupGraph AI</span>
        </div>
        <span className="tagline muted small">GraphRAG startup intelligence</span>
        <span className={`health health-${health}`} title={`API ${health === 'ok' ? 'online' : health === 'down' ? 'unreachable' : 'checking…'}`}>
          <span className="health-dot" />
          <span className="small">{health === 'ok' ? 'API online' : health === 'down' ? 'API offline' : 'Checking…'}</span>
        </span>
      </header>
      <nav className="sidebar" aria-label="Main">
        {NAV.map((n) => (
          <NavLink key={n.to} to={n.to} end={n.end} className={({ isActive }) => `nav-item ${isActive ? 'active' : ''}`}>
            <span className="nav-icon" aria-hidden="true">
              {n.icon}
            </span>
            {n.label}
          </NavLink>
        ))}
      </nav>
      {navOpen && <div className="scrim" onClick={() => setNavOpen(false)} />}
      <main className="main">
        <Outlet />
      </main>
    </div>
  );
}
