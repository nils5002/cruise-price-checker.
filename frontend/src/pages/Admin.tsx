import { useEffect, useState } from 'react';
import { api, artifactUrl } from '../lib/api';
import type { AdminError, AdminStatus, Meta } from '../types';
import { dateTime, statusLabel, statusTone } from '../lib/format';
import { Badge, Card, EmptyState, Notice, Spinner } from '../components/ui';

function bytes(value: number): string {
  if (value < 1024) return `${value} B`;
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`;
  return `${(value / 1024 / 1024).toFixed(1)} MB`;
}

export function Admin({ meta }: { meta: Meta | null }) {
  const [status, setStatus] = useState<AdminStatus | null>(null);
  const [errors, setErrors] = useState<AdminError[] | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const [debugScanId, setDebugScanId] = useState('');
  const [debug, setDebug] = useState<string | null>(null);
  const [feedback, setFeedback] = useState<string | null>(null);

  const load = () => {
    api.adminStatus().then(setStatus).catch((exc: Error) => setProblem(exc.message));
    api.adminErrors().then(setErrors).catch(() => setErrors([]));
  };

  useEffect(() => {
    load();
    const timer = window.setInterval(load, 20000);
    return () => window.clearInterval(timer);
  }, []);

  if (problem) {
    return (
      <Notice tone="bad" title="Adminbereich nicht verfügbar">
        {problem} – falls ein API-Key gesetzt ist, muss er oben rechts eingetragen werden.
      </Notice>
    );
  }
  if (!status) return <Spinner />;

  return (
    <div className="stack">
      <Card title="Systemstatus">
        <div className="stats-grid">
          <div className="stat">
            <span className="stat-label">Version</span>
            <strong className="stat-value">{status.version}</strong>
            <span className="stat-hint">{status.environment}</span>
          </div>
          <div className="stat">
            <span className="stat-label">Datenbank</span>
            <strong className="stat-value">{status.database_backend}</strong>
          </div>
          <div className="stat">
            <span className="stat-label">Playwright</span>
            <strong className="stat-value">{status.playwright_available ? 'verfügbar' : 'fehlt'}</strong>
            <span className="stat-hint">{status.headless ? 'headless' : 'sichtbarer Browser (Debug)'}</span>
          </div>
          <div className="stat">
            <span className="stat-label">Scans laufend</span>
            <strong className="stat-value">{status.queue.running.length}</strong>
            <span className="stat-hint">max. {status.queue.max_concurrent_scans} parallel</span>
          </div>
          <div className="stat">
            <span className="stat-label">Reisen / Scans</span>
            <strong className="stat-value">
              {status.counts.cruises} / {status.counts.scans}
            </strong>
            <span className="stat-hint">{status.counts.results} Einzelergebnisse</span>
          </div>
        </div>
      </Card>

      <div className="grid-2">
        <Card title="Scheduler">
          <ul className="kv">
            <li>
              <span>Aktiv</span>
              <strong>{status.scheduler.enabled ? (status.scheduler.running ? 'ja' : 'aktiviert, nicht gestartet') : 'nein'}</strong>
            </li>
            <li>
              <span>Prüfintervall</span>
              <strong>alle {status.scheduler.check_every_minutes} Minuten</strong>
            </li>
            <li>
              <span>Unterstützt</span>
              <strong>{status.scheduler.supported_intervals.join(', ')}</strong>
            </li>
            {status.scheduler.jobs.map((job) => (
              <li key={job.id}>
                <span>{job.id}</span>
                <strong>{dateTime(job.next_run)}</strong>
              </li>
            ))}
          </ul>
        </Card>

        <Card title="Limits (Rate Limiting)">
          <ul className="kv">
            {Object.entries(status.limits).map(([key, value]) => (
              <li key={key}>
                <span>{key.replace(/_/g, ' ')}</span>
                <strong>{String(value)}</strong>
              </li>
            ))}
          </ul>
        </Card>

        <Card title="Provider">
          <ul className="kv">
            {status.providers.map((provider) => (
              <li key={provider.key}>
                <span>{provider.label}</span>
                <Badge tone={provider.status === 'aktiv' ? 'ok' : 'muted'}>{provider.status}</Badge>
              </li>
            ))}
          </ul>
        </Card>

        <Card title="Proxyprofile">
          {status.proxy_profiles.length === 0 && (
            <EmptyState title="Keine Proxys konfiguriert">
              <span className="muted">
                Alle Tests laufen über die normale Internetverbindung. Proxys werden optional über
                PROXY_DE_1…3 in der .env gesetzt; Zugangsdaten werden nie angezeigt oder geloggt.
              </span>
            </EmptyState>
          )}
          {status.proxy_profiles.length > 0 && (
            <ul className="kv">
              {status.proxy_profiles.map((proxy) => (
                <li key={proxy.label}>
                  <span>{proxy.label}</span>
                  <Badge tone="ok">konfiguriert</Badge>
                </li>
              ))}
            </ul>
          )}
        </Card>

        <Card title="Benachrichtigungskanäle">
          <ul className="kv">
            {status.notification_channels.map((channel) => (
              <li key={channel.key}>
                <span>{channel.label}</span>
                <Badge tone={channel.configured ? 'ok' : 'muted'}>
                  {channel.configured ? 'konfiguriert' : 'nicht konfiguriert'}
                </Badge>
              </li>
            ))}
          </ul>
        </Card>

        <Card title="Speicher">
          <ul className="kv">
            {Object.entries(status.storage).map(([key, value]) => (
              <li key={key}>
                <span>{key}</span>
                <strong>
                  {value.files} Dateien · {bytes(value.bytes)}
                </strong>
              </li>
            ))}
          </ul>
        </Card>
      </div>

      <Card title="Flugvergleich">
        <Notice tone="info" title={status.flights.enabled ? 'aktiv' : 'vorbereitet, deaktiviert'}>
          {status.flights.note}
          <div className="muted small">
            Bevorzugte Flughäfen: {status.flights.preferred_airports.join(', ') || '–'}
          </div>
        </Notice>
      </Card>

      <Card title="Browserprofile" subtitle="Einheitliche Bedingungen, unterschiedliche Geräte">
        <div className="table-scroll">
          <table className="table small">
            <thead>
              <tr>
                <th>Profil</th>
                <th>Browser</th>
                <th>Gerät</th>
                <th>Viewport</th>
                <th>DPR</th>
                <th>Session</th>
                <th>User-Agent</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {status.profiles.map((profile) => (
                <tr key={profile.key}>
                  <td>
                    <strong>{profile.label}</strong>
                    <div className="muted small">{profile.description}</div>
                  </td>
                  <td>{profile.browser}</td>
                  <td>{profile.device}</td>
                  <td>
                    {profile.viewport.width}×{profile.viewport.height}
                  </td>
                  <td>{profile.device_scale_factor}</td>
                  <td>{profile.session_type === 'returning' ? 'persistent' : 'isoliert'}</td>
                  <td className="mono tiny">{profile.user_agent ?? '–'}</td>
                  <td>
                    {profile.persist_state && (
                      <button
                        type="button"
                        className="btn btn-link danger"
                        onClick={async () => {
                          const result = await api.resetProfile(profile.key);
                          setFeedback(result.detail);
                        }}
                      >
                        Session zurücksetzen
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {feedback && <Notice tone="info">{feedback}</Notice>}
      </Card>

      <Card title="Fehler" subtitle="Nicht erfolgreiche Einzelergebnisse (neueste zuerst)">
        {errors === null && <Spinner />}
        {errors !== null && errors.length === 0 && <EmptyState title="Keine Fehler protokolliert" />}
        {errors !== null && errors.length > 0 && (
          <div className="table-scroll">
            <table className="table small">
              <thead>
                <tr>
                  <th>Zeit</th>
                  <th>Scan</th>
                  <th>Profil</th>
                  <th>Status</th>
                  <th>Seitentyp</th>
                  <th>Meldung</th>
                  <th>Screenshot</th>
                </tr>
              </thead>
              <tbody>
                {errors.map((row) => (
                  <tr key={row.id}>
                    <td>{dateTime(row.created_at)}</td>
                    <td>#{row.scan_id}</td>
                    <td>{row.profile}</td>
                    <td>
                      <Badge tone={statusTone(row.status)}>{statusLabel(row.status)}</Badge>
                    </td>
                    <td>{row.page_type ?? '–'}</td>
                    <td className="tiny">{row.error || '–'}</td>
                    <td>
                      {row.screenshot_path ? (
                        <a href={artifactUrl(row.screenshot_path)} target="_blank" rel="noreferrer">
                          ansehen
                        </a>
                      ) : (
                        '–'
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      <Card
        title="Debug-Modus"
        subtitle="Aktuelle URL, erkannter Seitentyp, gefundene Preise, Playwright-Schritte, Fehler – ohne Secrets"
      >
        <div className="row wrap gap">
          <input
            placeholder="Scan-ID"
            value={debugScanId}
            onChange={(event) => setDebugScanId(event.target.value)}
            style={{ maxWidth: 160 }}
          />
          <button
            type="button"
            className="btn btn-primary"
            onClick={async () => {
              const id = Number(debugScanId);
              if (!id) return;
              try {
                const payload = await api.adminDebug(id);
                setDebug(JSON.stringify(payload, null, 2));
              } catch (exc) {
                setDebug(exc instanceof Error ? exc.message : 'Fehler');
              }
            }}
          >
            Debug-Daten laden
          </button>
        </div>
        {debug && <pre className="code">{debug}</pre>}
      </Card>

      {meta && (
        <Card title="Einheitliche Testbedingungen">
          <ul className="kv">
            {Object.entries(meta.unified_conditions).map(([key, value]) => (
              <li key={key}>
                <span>{key}</span>
                <strong>{String(value)}</strong>
              </li>
            ))}
            <li>
              <span>erlaubte Domains</span>
              <strong>{meta.allowed_domains.join(', ')}</strong>
            </li>
          </ul>
        </Card>
      )}
    </div>
  );
}
