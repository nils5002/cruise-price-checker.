import { useCallback, useEffect, useState } from 'react';
import { api, ApiError } from '../lib/api';
import type { Alert, CruiseDetailPayload, Meta, ScanDetail } from '../types';
import {
  dateTime,
  isoDate,
  money,
  percent,
  relativeTime,
  signedMoney,
  statusLabel,
  statusTone,
  VERDICT_LABELS,
} from '../lib/format';
import { Badge, Card, EmptyState, Field, Notice, Spinner, Stat } from '../components/ui';
import { PriceChart } from '../components/PriceChart';
import { ProfileComparison } from '../components/ProfileComparison';
import { ScreenshotGallery } from '../components/ScreenshotGallery';
import { ScanOptionsForm, defaultOptions, toScanOptions, type OptionsState } from '../components/ScanOptionsForm';

export function CruiseDetail({
  cruiseId,
  meta,
  onNavigate,
}: {
  cruiseId: number;
  meta: Meta | null;
  onNavigate: (hash: string) => void;
}) {
  const [data, setData] = useState<CruiseDetailPayload | null>(null);
  const [scan, setScan] = useState<ScanDetail | null>(null);
  const [selectedScanId, setSelectedScanId] = useState<number | null>(null);
  const [options, setOptions] = useState<OptionsState>(defaultOptions(meta));
  const [showOptions, setShowOptions] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => setOptions(defaultOptions(meta)), [meta]);

  const load = useCallback(async () => {
    try {
      const payload = await api.cruise(cruiseId);
      setData(payload);
      const target = selectedScanId ?? payload.scans[0]?.id ?? null;
      if (target) {
        setSelectedScanId(target);
        setScan(await api.scan(target));
      }
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : 'Laden fehlgeschlagen');
    }
  }, [cruiseId, selectedScanId]);

  useEffect(() => {
    load();
  }, [load]);

  useEffect(() => {
    const active = scan && (scan.status === 'RUNNING' || scan.status === 'QUEUED');
    if (!active) return;
    const timer = window.setInterval(load, 8000);
    return () => window.clearInterval(timer);
  }, [scan, load]);

  const startScan = async () => {
    setBusy(true);
    setError(null);
    setMessage(null);
    try {
      const created = await api.startScan(cruiseId, toScanOptions(options));
      setSelectedScanId(created.id);
      setMessage(`Scan ${created.id} wurde eingereiht. Die Tests laufen bewusst langsam und nacheinander.`);
      await load();
    } catch (exc) {
      if (exc instanceof ApiError && exc.status === 429) setError(exc.message);
      else setError(exc instanceof Error ? exc.message : 'Scan konnte nicht gestartet werden');
    } finally {
      setBusy(false);
    }
  };

  if (!data) {
    return error ? <Notice tone="bad" title="Fehler">{error}</Notice> : <Spinner />;
  }

  const { cruise, overview, history, scans, alerts } = data;
  const analysis = scan?.analysis ?? data.latest_analysis;
  const lowest = history.reduce<number | null>(
    (acc, point) => (point.lowest_price !== null && (acc === null || point.lowest_price < acc) ? point.lowest_price : acc),
    null,
  );
  const highest = history.reduce<number | null>(
    (acc, point) => (point.highest_price !== null && (acc === null || point.highest_price > acc) ? point.highest_price : acc),
    null,
  );
  const lowestPoint = history.find((point) => point.lowest_price !== null && point.lowest_price === lowest) ?? null;

  return (
    <div className="stack">
      <div className="row wrap between">
        <div>
          <button type="button" className="btn btn-ghost" onClick={() => onNavigate('#/')}>
            ← Übersicht
          </button>
          <h1 className="page-title">{cruise.title ?? `Reise ${cruise.id}`}</h1>
          <p className="muted">
            {cruise.ship ?? 'Schiff unbekannt'} · {isoDate(cruise.departure_date)} bis {isoDate(cruise.return_date)}
            {cruise.nights ? ` · ${cruise.nights} Nächte` : ''}
            {cruise.origin ? ` · ab ${cruise.origin}` : ''}
          </p>
          <p className="muted small">
            <a href={cruise.url} target="_blank" rel="noreferrer">
              Original-Angebot öffnen
            </a>
            {' · '}
            {cruise.passenger_count ?? '?'} Reisende · {cruise.cabin_type ?? 'Kabinenart unbekannt'} ·{' '}
            {cruise.flight_included === null ? 'Flug unbekannt' : cruise.flight_included ? 'mit Flug' : 'ohne Flug'}
          </p>
        </div>
        <div className="row wrap gap">
          <select
            value={cruise.schedule_interval}
            onChange={async (event) => {
              await api.updateCruise(cruiseId, { schedule_interval: event.target.value });
              load();
            }}
          >
            <option value="manual">manuell</option>
            <option value="6h">alle 6 Stunden</option>
            <option value="12h">alle 12 Stunden</option>
            <option value="daily">täglich</option>
          </select>
          <button type="button" className="btn btn-ghost" onClick={() => setShowOptions((value) => !value)}>
            Testoptionen
          </button>
          <button type="button" className="btn btn-primary" onClick={startScan} disabled={busy}>
            {busy ? 'Startet …' : 'Preis erneut prüfen'}
          </button>
        </div>
      </div>

      {showOptions && (
        <Card title="Testoptionen">
          <ScanOptionsForm meta={meta} state={options} onChange={setOptions} />
        </Card>
      )}

      {message && <Notice tone="ok">{message}</Notice>}
      {error && <Notice tone="bad" title="Fehler">{error}</Notice>}

      <div className="stats-grid">
        <Stat
          label="Aktueller Bestpreis"
          value={<span className="big">{money(overview.current_price, cruise.currency)}</span>}
          hint={overview.last_checked_at ? `Stand: ${dateTime(overview.last_checked_at)}` : 'noch kein Check'}
          tone="ok"
        />
        <Stat label="Bisheriger Tiefstpreis" value={money(lowest, cruise.currency)} hint={lowestPoint ? dateTime(lowestPoint.timestamp) : '–'} />
        <Stat label="Bisheriger Höchstpreis" value={money(highest, cruise.currency)} />
        <Stat
          label="Differenz"
          value={lowest !== null && highest !== null ? money(highest - lowest, cruise.currency) : '–'}
          hint={lowest !== null && highest !== null && highest > 0 ? percent(((highest - lowest) / highest) * 100) : undefined}
        />
        <Stat
          label="Nächster Check"
          value={cruise.schedule_interval === 'manual' ? 'manuell' : relativeTime(overview.next_check_at)}
          hint={cruise.schedule_interval === 'manual' ? undefined : dateTime(overview.next_check_at)}
        />
      </div>

      {analysis && (
        <Card
          title={analysis.headline}
          subtitle={VERDICT_LABELS[analysis.verdict] ?? analysis.verdict}
          actions={
            analysis.spread_abs !== undefined && analysis.spread_abs > 0 ? (
              <Badge tone="info">
                Ersparnis gegenüber teuerstem Ergebnis: {money(analysis.spread_abs, analysis.currency)} ·{' '}
                {percent(analysis.spread_pct ?? 0)}
              </Badge>
            ) : undefined
          }
        >
          <div className="stack">
            {analysis.interpretation.map((text, index) => (
              <p key={index} className="interpretation">
                {text}
              </p>
            ))}
            {analysis.reproducibility?.text && (
              <Badge tone={analysis.reproducibility.status === 'reproduced' ? 'ok' : 'warn'}>
                {analysis.reproducibility.text}
              </Badge>
            )}
            {analysis.warnings.map((warning, index) => (
              <Notice key={index} tone="warn">
                {warning}
              </Notice>
            ))}
            {analysis.cause_hypotheses.length > 0 && (
              <div className="stack-sm">
                <h3>Mögliche Ursachen (Hypothesen, nicht bewiesen)</h3>
                <ul className="causes">
                  {analysis.cause_hypotheses.map((entry) => (
                    <li key={entry.profile}>
                      <strong>{entry.profile_label}</strong> {signedMoney(entry.diff)} –{' '}
                      {entry.possible_causes.join(', ')}
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        </Card>
      )}

      <Card title="Preisverlauf" subtitle={`${history.length} gespeicherte Messpunkte`}>
        <PriceChart points={history} currency={cruise.currency} />
        {history.length > 0 && (
          <details>
            <summary>Messwerte als Tabelle</summary>
            <div className="table-scroll">
              <table className="table">
                <thead>
                  <tr>
                    <th>Datum</th>
                    <th className="num">niedrigster Preis</th>
                    <th className="num">höchster Preis</th>
                    <th>günstigstes Profil</th>
                    <th>Scan</th>
                  </tr>
                </thead>
                <tbody>
                  {[...history].reverse().map((point) => (
                    <tr key={point.id}>
                      <td>{dateTime(point.timestamp)}</td>
                      <td className="num">{money(point.lowest_price, point.currency)}</td>
                      <td className="num">{money(point.highest_price, point.currency)}</td>
                      <td>{point.lowest_profile ?? '–'}</td>
                      <td>
                        {point.scan_id ? (
                          <button type="button" className="btn btn-link" onClick={() => setSelectedScanId(point.scan_id)}>
                            #{point.scan_id}
                          </button>
                        ) : (
                          '–'
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </details>
        )}
      </Card>

      <Card
        title="Browserprofil-Vergleich"
        subtitle={
          scan
            ? `Scan #${scan.id} · ${statusLabel(scan.status)} · Runden ${scan.rounds_completed}/${scan.rounds_planned} · ${dateTime(
                scan.started_at,
              )}`
            : 'Kein Scan ausgewählt'
        }
        actions={
          <select
            value={selectedScanId ?? ''}
            onChange={async (event) => {
              const id = Number(event.target.value);
              setSelectedScanId(id);
              setScan(await api.scan(id));
            }}
          >
            {scans.map((item) => (
              <option key={item.id} value={item.id}>
                #{item.id} · {dateTime(item.started_at)} · {statusLabel(item.status)}
              </option>
            ))}
          </select>
        }
      >
        {!scan && <EmptyState title="Noch kein Scan vorhanden" />}
        {scan && scan.status === 'QUEUED' && <Spinner label="Scan wartet in der Warteschlange …" />}
        {scan && scan.status === 'RUNNING' && (
          <Spinner label="Tests laufen nacheinander (bewusst langsam, um die Zielseite zu schonen) …" />
        )}
        {scan?.error && <Notice tone="bad" title="Scan-Fehler">{scan.error}</Notice>}
        {scan?.analysis && <ProfileComparison analysis={scan.analysis} />}
        {scan && !scan.analysis && scan.status === 'DONE' && (
          <Notice tone="warn">Für diesen Scan liegt keine Auswertung vor.</Notice>
        )}
        {scan && scan.results.length > 0 && (
          <details>
            <summary>Preisdetails je Test</summary>
            <div className="table-scroll">
              <table className="table small">
                <thead>
                  <tr>
                    <th>Profil</th>
                    <th>Runde</th>
                    <th className="num">Einstieg</th>
                    <th className="num">pro Person</th>
                    <th className="num">Kabine</th>
                    <th className="num">Service</th>
                    <th className="num">Flug</th>
                    <th className="num">Transfer</th>
                    <th className="num">Getränke</th>
                    <th className="num">Extras</th>
                    <th className="num">Rabatt</th>
                    <th className="num">Gesamt</th>
                    <th className="num">Endpreis</th>
                    <th>Aktion</th>
                    <th>Tiefster Schritt</th>
                  </tr>
                </thead>
                <tbody>
                  {scan.results.map((result) => (
                    <tr key={result.id}>
                      <td>{result.profile_label}</td>
                      <td>{result.round}</td>
                      <td className="num">{money(result.starting_price)}</td>
                      <td className="num">{money(result.price_per_person)}</td>
                      <td className="num">{money(result.cabin_price)}</td>
                      <td className="num">{money(result.service_fee)}</td>
                      <td className="num">{money(result.flight_price)}</td>
                      <td className="num">{money(result.transfer_price)}</td>
                      <td className="num">{money(result.drinks_package_price)}</td>
                      <td className="num">{money(result.extras_price)}</td>
                      <td className="num">{money(result.discount)}</td>
                      <td className="num">{money(result.total_price)}</td>
                      <td className="num">
                        <strong>{money(result.final_price)}</strong>
                      </td>
                      <td>{result.promo_code ?? '–'}</td>
                      <td>
                        {result.deepest_step ?? '–'}
                        <div className="muted small">{statusLabel(result.status)}</div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </details>
        )}
      </Card>

      {scan && scan.results.length > 0 && (
        <Card title="Screenshots & HTML-Snapshots" subtitle="Beweise je Schritt und Profil">
          <ScreenshotGallery results={scan.results} />
        </Card>
      )}

      <AlertsCard cruiseId={cruiseId} alerts={alerts} meta={meta} onChanged={load} />

      <Card title="Scans" subtitle="Alle Durchläufe dieser Reise">
        <div className="table-scroll">
          <table className="table small">
            <thead>
              <tr>
                <th>Scan</th>
                <th>Start</th>
                <th>Ende</th>
                <th>Auslöser</th>
                <th>Runden</th>
                <th>Status</th>
                <th>Ergebnis</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {scans.map((item) => (
                <tr key={item.id}>
                  <td>#{item.id}</td>
                  <td>{dateTime(item.started_at)}</td>
                  <td>{dateTime(item.finished_at)}</td>
                  <td>{item.trigger}</td>
                  <td>
                    {item.rounds_completed}/{item.rounds_planned}
                  </td>
                  <td>
                    <Badge tone={statusTone(item.status)}>{statusLabel(item.status)}</Badge>
                  </td>
                  <td>{item.analysis ? VERDICT_LABELS[item.analysis.verdict] ?? item.analysis.verdict : '–'}</td>
                  <td>
                    <button
                      type="button"
                      className="btn btn-link"
                      onClick={async () => {
                        setSelectedScanId(item.id);
                        setScan(await api.scan(item.id));
                      }}
                    >
                      anzeigen
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>

      <Card title="Reise entfernen">
        <button
          type="button"
          className="btn btn-danger"
          onClick={async () => {
            if (!window.confirm('Reise samt Scans, Screenshots-Verweisen und Verlauf löschen?')) return;
            await api.deleteCruise(cruiseId);
            onNavigate('#/');
          }}
        >
          Reise löschen
        </button>
      </Card>
    </div>
  );
}

function AlertsCard({
  cruiseId,
  alerts,
  meta,
  onChanged,
}: {
  cruiseId: number;
  alerts: Alert[];
  meta: Meta | null;
  onChanged: () => void;
}) {
  const [channel, setChannel] = useState('telegram');
  const [target, setTarget] = useState('');
  const [threshold, setThreshold] = useState('');
  const [drop, setDrop] = useState('');
  const [feedback, setFeedback] = useState<string | null>(null);

  const create = async () => {
    setFeedback(null);
    try {
      await api.createAlert(cruiseId, {
        channel,
        target: target || null,
        threshold_total: threshold ? Number(threshold) : null,
        drop_percent: drop ? Number(drop) : null,
        enabled: true,
      });
      setTarget('');
      setThreshold('');
      setDrop('');
      onChanged();
    } catch (exc) {
      setFeedback(exc instanceof Error ? exc.message : 'Anlegen fehlgeschlagen');
    }
  };

  return (
    <Card title="Preisalarm" subtitle="Benachrichtigung, wenn der Gesamtpreis unter eine Schwelle fällt">
      <div className="stack">
        {alerts.length === 0 && <EmptyState title="Kein Preisalarm eingerichtet" />}
        {alerts.length > 0 && (
          <div className="table-scroll">
            <table className="table small">
              <thead>
                <tr>
                  <th>Kanal</th>
                  <th>Ziel</th>
                  <th className="num">Schwelle</th>
                  <th className="num">Rückgang</th>
                  <th>Letzte Auslösung</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {alerts.map((alert) => (
                  <tr key={alert.id}>
                    <td>{alert.channel}</td>
                    <td>{alert.target ?? 'Standard aus .env'}</td>
                    <td className="num">{money(alert.threshold_total)}</td>
                    <td className="num">{alert.drop_percent ? `${alert.drop_percent} %` : '–'}</td>
                    <td>{dateTime(alert.last_triggered_at)}</td>
                    <td className="row gap">
                      <button
                        type="button"
                        className="btn btn-link"
                        onClick={async () => {
                          const result = await api.testAlert(alert.id);
                          setFeedback(result.detail);
                        }}
                      >
                        testen
                      </button>
                      <button
                        type="button"
                        className="btn btn-link danger"
                        onClick={async () => {
                          await api.deleteAlert(alert.id);
                          onChanged();
                        }}
                      >
                        löschen
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        <div className="options-grid">
          <Field label="Kanal">
            <select value={channel} onChange={(event) => setChannel(event.target.value)}>
              {(meta?.notification_channels ?? [{ key: 'telegram', label: 'Telegram', configured: false }]).map(
                (item) => (
                  <option key={item.key} value={item.key}>
                    {item.label}
                    {item.configured ? '' : ' (nicht konfiguriert)'}
                  </option>
                ),
              )}
            </select>
          </Field>
          <Field label="Ziel" hint="E-Mail-Adresse, Telegram-Chat-ID oder Webhook-URL (optional)">
            <input value={target} onChange={(event) => setTarget(event.target.value)} placeholder="optional" />
          </Field>
          <Field label="Gesamtpreis unter (€)">
            <input
              type="number"
              min={0}
              step={10}
              value={threshold}
              onChange={(event) => setThreshold(event.target.value)}
              placeholder="2800"
            />
          </Field>
          <Field label="oder Rückgang um (%)">
            <input
              type="number"
              min={0.1}
              step={0.5}
              value={drop}
              onChange={(event) => setDrop(event.target.value)}
              placeholder="5"
            />
          </Field>
        </div>
        <div>
          <button type="button" className="btn btn-primary" onClick={create}>
            Preisalarm speichern
          </button>
        </div>
        {feedback && <Notice tone="info">{feedback}</Notice>}
      </div>
    </Card>
  );
}
