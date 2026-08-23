import { useEffect, useState } from 'react';
import { api, getApiKey, setApiKey } from './lib/api';
import type { Meta } from './types';
import { Dashboard } from './pages/Dashboard';
import { CruiseDetail } from './pages/CruiseDetail';
import { Admin } from './pages/Admin';
import { Notice } from './components/ui';

type Route = { name: 'dashboard' } | { name: 'cruise'; id: number } | { name: 'admin' };

function parseRoute(hash: string): Route {
  const clean = hash.replace(/^#\/?/, '');
  if (clean.startsWith('admin')) return { name: 'admin' };
  const match = clean.match(/^cruise\/(\d+)$/);
  if (match) return { name: 'cruise', id: Number(match[1]) };
  return { name: 'dashboard' };
}

export default function App() {
  const [route, setRoute] = useState<Route>(parseRoute(window.location.hash));
  const [meta, setMeta] = useState<Meta | null>(null);
  const [metaError, setMetaError] = useState<string | null>(null);
  const [keyInput, setKeyInput] = useState(getApiKey());
  const [showKey, setShowKey] = useState(false);

  useEffect(() => {
    const onHashChange = () => setRoute(parseRoute(window.location.hash));
    window.addEventListener('hashchange', onHashChange);
    return () => window.removeEventListener('hashchange', onHashChange);
  }, []);

  useEffect(() => {
    api
      .meta()
      .then(setMeta)
      .catch((exc: Error) => setMetaError(exc.message));
  }, []);

  const navigate = (hash: string) => {
    window.location.hash = hash;
    setRoute(parseRoute(hash));
  };

  return (
    <div className="app">
      <header className="topbar">
        <div className="brand" onClick={() => navigate('#/')}>
          <span className="logo" aria-hidden="true">⚓</span>
          <div>
            <strong>Cruise Price Checker</strong>
            <span className="muted small">
              {meta ? `v${meta.version} · ${meta.environment}` : 'Preise unter neutralen Browserbedingungen vergleichen'}
            </span>
          </div>
        </div>
        <nav className="nav">
          <button
            type="button"
            className={route.name === 'dashboard' ? 'active' : ''}
            onClick={() => navigate('#/')}
          >
            Dashboard
          </button>
          <button type="button" className={route.name === 'admin' ? 'active' : ''} onClick={() => navigate('#/admin')}>
            Admin
          </button>
          <button type="button" onClick={() => setShowKey((value) => !value)}>
            API-Key
          </button>
        </nav>
      </header>

      {showKey && (
        <div className="keybar">
          <label>
            API-Key (nur nötig, wenn API_KEY in der .env gesetzt ist)
            <input
              type="password"
              value={keyInput}
              onChange={(event) => setKeyInput(event.target.value)}
              placeholder="X-API-Key"
            />
          </label>
          <button
            type="button"
            className="btn btn-primary"
            onClick={() => {
              setApiKey(keyInput.trim());
              setShowKey(false);
              window.location.reload();
            }}
          >
            Speichern
          </button>
        </div>
      )}

      <main className="content">
        {metaError && (
          <Notice tone="bad" title="Backend nicht erreichbar">
            {metaError}
          </Notice>
        )}
        {route.name === 'dashboard' && <Dashboard meta={meta} onNavigate={navigate} />}
        {route.name === 'cruise' && <CruiseDetail cruiseId={route.id} meta={meta} onNavigate={navigate} />}
        {route.name === 'admin' && <Admin meta={meta} />}
      </main>

      <footer className="footer">
        <span className="muted small">
          Nur lesende Preisvergleiche auf öffentlich zugänglichen Angebotsseiten. Keine Umgehung von
          CAPTCHAs oder Bot-Schutz, keine Logins, keine Buchungen. Blockierte Tests werden als
          „BLOCKED / CAPTCHA“ ausgewiesen.
        </span>
      </footer>
    </div>
  );
}
