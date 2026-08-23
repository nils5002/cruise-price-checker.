import { useEffect, useState } from 'react';
import type { FormEvent } from 'react';
import { api, ApiError } from '../lib/api';
import type { CruiseOverview, Meta, ParsedUrl } from '../types';
import { dateTime, isoDate, money, relativeTime, signedMoney, statusLabel, statusTone, VERDICT_LABELS } from '../lib/format';
import { Badge, Card, EmptyState, Field, Notice, Spinner } from '../components/ui';
import { ScanOptionsForm, defaultOptions, toScanOptions, type OptionsState } from '../components/ScanOptionsForm';

export function Dashboard({ meta, onNavigate }: { meta: Meta | null; onNavigate: (hash: string) => void }) {
  const [url, setUrl] = useState('');
  const [preview, setPreview] = useState<ParsedUrl | null>(null);
  const [previewError, setPreviewError] = useState<string | null>(null);
  const [options, setOptions] = useState<OptionsState>(defaultOptions(meta));
  const [schedule, setSchedule] = useState('manual');
  const [showOptions, setShowOptions] = useState(false);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [cruises, setCruises] = useState<CruiseOverview[] | null>(null);

  useEffect(() => {
    setOptions(defaultOptions(meta));
  }, [meta]);

  const load = () => {
    api
      .cruises()
      .then(setCruises)
      .catch((exc: Error) => setError(exc.message));
  };

  useEffect(() => {
    load();
    const timer = window.setInterval(load, 15000);
    return () => window.clearInterval(timer);
  }, []);

  const checkUrl = async (value: string) => {
    setPreview(null);
    setPreviewError(null);
    if (!value.trim()) return;
    try {
      setPreview(await api.parseUrl(value.trim()));
    } catch (exc) {
      setPreviewError(exc instanceof Error ? exc.message : 'Link konnte nicht gelesen werden.');
    }
  };

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setError(null);
    setMessage(null);
    try {
      const result = await api.createCruise({
        url: url.trim(),
        start_scan: true,
        schedule_interval: schedule,
        options: toScanOptions(options),
      });
      setMessage(
        result.warning
          ? result.warning
          : `Preisvergleich gestartet (Scan ${result.scan_id ?? '–'}). Ergebnisse erscheinen laufend in der Detailansicht.`,
      );
      setUrl('');
      setPreview(null);
      load();
      if (result.cruise?.id) onNavigate(`#/cruise/${result.cruise.id}`);
    } catch (exc) {
      if (exc instanceof ApiError && exc.status === 401) {
        setError('Nicht autorisiert – bitte oben rechts den API-Key eintragen.');
      } else {
        setError(exc instanceof Error ? exc.message : 'Unbekannter Fehler');
      }
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="stack">
      <Card
        title="Preisvergleich starten"
        subtitle="MSC-Buchungslink einfügen. Jeder Test läuft in einem vollständig getrennten Browserprofil."
      >
        <form onSubmit={submit} className="stack">
          <Field
            label="MSC Buchungslink"
            hint={
              meta
                ? `Erlaubte Domains: ${meta.allowed_domains.join(', ')}`
                : 'Nur offizielle Anbieter-Domains werden geöffnet.'
            }
          >
            <input
              type="text"
              inputMode="url"
              placeholder="https://www.msccruises.de/booking?..."
              value={url}
              onChange={(event) => setUrl(event.target.value)}
              onBlur={(event) => checkUrl(event.target.value)}
              required
            />
          </Field>

          {previewError && <Notice tone="bad" title="Link nicht verwendbar">{previewError}</Notice>}

          {preview && (
            <div className="parsed-grid">
              {(
                [
                  ['Reise-ID', preview.external_id],
                  ['Schiff', preview.ship],
                  ['Start', isoDate(preview.departure_date)],
                  ['Ende', isoDate(preview.return_date)],
                  ['Nächte', preview.nights],
                  ['Abfahrtshafen', preview.origin],
                  ['Ziel', preview.destination],
                  ['Kabinenart', preview.cabin_type],
                  ['Kabinenkategorie', preview.cabin_category],
                  ['Erwachsene', preview.adults],
                  ['Kinder', preview.children],
                  ['Tarif', preview.rate_code],
                  ['Preiscode', preview.price_code],
                  ['Flug enthalten', preview.flight_included === null ? null : preview.flight_included ? 'ja' : 'nein'],
                ] as [string, string | number | null | undefined][]
              ).map(([label, value]) => (
                <div key={label} className="parsed-item">
                  <span className="muted small">{label}</span>
                  <strong>{value === null || value === undefined || value === '–' ? 'aus Seite lesen' : String(value)}</strong>
                </div>
              ))}
            </div>
          )}

          <div className="row wrap gap">
            <Field label="Automatische Checks">
              <select value={schedule} onChange={(event) => setSchedule(event.target.value)}>
                <option value="manual">manuell</option>
                <option value="6h">alle 6 Stunden</option>
                <option value="12h">alle 12 Stunden</option>
                <option value="daily">täglich</option>
              </select>
            </Field>
            <button type="button" className="btn btn-ghost" onClick={() => setShowOptions((value) => !value)}>
              {showOptions ? 'Testoptionen ausblenden' : 'Testoptionen anzeigen'}
            </button>
            <button type="submit" className="btn btn-primary" disabled={busy || !url.trim()}>
              {busy ? 'Startet …' : 'Preisvergleich starten'}
            </button>
          </div>

          {showOptions && <ScanOptionsForm meta={meta} state={options} onChange={setOptions} />}
        </form>

        {message && <Notice tone="ok">{message}</Notice>}
        {error && <Notice tone="bad" title="Fehler">{error}</Notice>}
      </Card>

      <Card title="Aktuell überwachte Reisen" subtitle="Preise, Veränderung und geplante Checks">
        {cruises === null && <Spinner />}
        {cruises !== null && cruises.length === 0 && (
          <EmptyState title="Noch keine Reise gespeichert">
            <span className="muted">Füge oben einen Buchungslink ein, um den ersten Vergleich zu starten.</span>
          </EmptyState>
        )}
        {cruises !== null && cruises.length > 0 && (
          <div className="table-scroll">
            <table className="table">
              <thead>
                <tr>
                  <th>Reise</th>
                  <th>Schiff</th>
                  <th>Zeitraum</th>
                  <th className="num">Bisher günstigster</th>
                  <th className="num">Aktueller Preis</th>
                  <th className="num">Veränderung</th>
                  <th>Letzter Check</th>
                  <th>Nächster Check</th>
                  <th>Ergebnis</th>
                </tr>
              </thead>
              <tbody>
                {cruises.map((cruise) => (
                  <tr key={cruise.id} className="clickable" onClick={() => onNavigate(`#/cruise/${cruise.id}`)}>
                    <td>
                      <strong>{cruise.title ?? `Reise ${cruise.id}`}</strong>
                      <div className="muted small">
                        {cruise.provider.toUpperCase()} · {cruise.passenger_count ?? '?'} Reisende
                        {cruise.cabin_type ? ` · ${cruise.cabin_type}` : ''}
                      </div>
                    </td>
                    <td>{cruise.ship ?? '–'}</td>
                    <td>
                      {isoDate(cruise.departure_date)}
                      {cruise.return_date ? ` – ${isoDate(cruise.return_date)}` : ''}
                    </td>
                    <td className="num">
                      <strong>{money(cruise.best_price_ever, cruise.currency)}</strong>
                    </td>
                    <td className="num">{money(cruise.current_price, cruise.currency)}</td>
                    <td className="num">
                      {cruise.change_since_previous === null ? (
                        '–'
                      ) : (
                        <Badge tone={cruise.change_since_previous <= 0 ? 'ok' : 'bad'}>
                          {signedMoney(cruise.change_since_previous)}
                        </Badge>
                      )}
                    </td>
                    <td title={dateTime(cruise.last_checked_at)}>{relativeTime(cruise.last_checked_at)}</td>
                    <td title={dateTime(cruise.next_check_at)}>
                      {cruise.schedule_interval === 'manual' ? 'manuell' : relativeTime(cruise.next_check_at)}
                    </td>
                    <td>
                      {cruise.last_scan_status && (
                        <Badge tone={statusTone(cruise.last_scan_status)}>{statusLabel(cruise.last_scan_status)}</Badge>
                      )}
                      {cruise.last_verdict && (
                        <div className="muted small">{VERDICT_LABELS[cruise.last_verdict] ?? cruise.last_verdict}</div>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </div>
  );
}
