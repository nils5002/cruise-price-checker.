import type { Analysis } from '../types';
import { COOKIE_LABELS, money, signedMoney, statusLabel, statusTone } from '../lib/format';
import { Badge, Notice } from './ui';

const APPLIED_LABELS: Record<string, string> = {
  nur_notwendige: 'necessary',
  nur_notwendige_ueber_einstellungen: 'über Einstellungen gespeichert',
  alle_akzeptiert: 'all',
  banner_ignoriert: 'none',
  banner_ignoriert_overlay_blockiert: 'Banner offen, Overlay aktiv',
  kein_banner: 'kein Banner vorhanden',
  banner_erkannt_aber_nicht_bedienbar: 'Banner nicht bedienbar',
};

/**
 * Zusatzhinweis zur Cookie-Spalte -- nur wenn die angewendete Variante von der
 * angeforderten abweicht (keine Dopplung wie "nur notwendige / nur notwendige").
 */
function appliedNote(requested: string, applied: string | null): string | null {
  if (!applied) return null;
  const mapped = APPLIED_LABELS[applied];
  if (mapped === requested) return null;
  return mapped ?? applied.replace(/_/g, ' ');
}

/** Profile comparison table -- the core result view. */
export function ProfileComparison({ analysis }: { analysis: Analysis }) {
  const currency = analysis.currency || 'EUR';
  const rounds = Object.keys(
    analysis.rows.reduce<Record<string, true>>((acc, row) => {
      Object.keys(row.prices_by_round ?? {}).forEach((key) => {
        acc[key] = true;
      });
      return acc;
    }, {}),
  ).sort();
  const showRounds = rounds.length > 1;

  return (
    <div className="stack">
      {analysis.comparable === false && (
        <Notice tone="warn" title="Nicht direkt vergleichbar">
          Die Ergebnisse gehören zu unterschiedlichen Angeboten. Preise werden deshalb nicht als
          Preisunterschied interpretiert.
        </Notice>
      )}
      <div className="table-scroll">
        <table className="table">
          <thead>
            <tr>
              <th>Profil</th>
              <th>Gerät</th>
              <th>Browser</th>
              <th>Cookies</th>
              <th>Einstieg</th>
              <th>Proxy</th>
              <th>Tarif</th>
              {showRounds && rounds.map((round) => <th key={round}>Runde {round}</th>)}
              <th className="num">Preis</th>
              <th className="num">Differenz</th>
              <th>Status</th>
            </tr>
          </thead>
          <tbody>
            {analysis.rows.map((row) => (
              <tr key={row.key} className={row.is_cheapest ? 'row-best' : row.is_most_expensive ? 'row-worst' : ''}>
                <td>
                  <strong>{row.profile_label}</strong>
                  <div className="muted small">
                    {row.session_type === 'returning' ? 'gespeicherte Session' : 'frische Session'}
                    {row.identity_group && (analysis.identity_groups?.length ?? 0) > 1
                      ? ` · Angebot ${row.identity_group}`
                      : ''}
                  </div>
                </td>
                <td>{row.device === 'mobile' ? 'Mobile' : 'Desktop'}</td>
                <td>{row.browser}</td>
                <td title={row.cookie_mode_applied ?? undefined}>
                  {COOKIE_LABELS[row.cookie_mode] ?? row.cookie_mode}
                  {appliedNote(row.cookie_mode, row.cookie_mode_applied) && (
                    <div className="muted small">
                      {appliedNote(row.cookie_mode, row.cookie_mode_applied)}
                    </div>
                  )}
                </td>
                <td>{row.referrer === 'direct' ? 'Direkt' : row.referrer}</td>
                <td>{row.proxy_name ?? 'direkt'}</td>
                <td>{row.tariff ?? '–'}</td>
                {showRounds &&
                  rounds.map((round) => (
                    <td key={round} className="num">
                      {money(row.prices_by_round?.[round] ?? null, currency)}
                    </td>
                  ))}
                <td className="num">
                  <strong>{money(row.price, currency)}</strong>
                </td>
                <td className="num">
                  {row.is_cheapest ? (
                    <Badge tone="ok">günstigster</Badge>
                  ) : (
                    signedMoney(row.diff_to_cheapest)
                  )}
                </td>
                <td>
                  <Badge tone={statusTone(row.status)} title={row.error ?? undefined}>
                    {statusLabel(row.status)}
                  </Badge>
                  {!row.price_stable && row.rounds_with_price > 1 && (
                    <div className="muted small">Preis wechselte zwischen den Runden</div>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {analysis.identity_differences && analysis.identity_differences.length > 0 && (
        <div className="stack-sm">
          <h3>Unterschiede der Angebote</h3>
          {analysis.identity_differences.map((entry) => (
            <div key={entry.group_id} className="diff-box">
              <div className="muted small">
                {entry.members.join(', ')} vs. {entry.reference_members.join(', ')}
              </div>
              <ul>
                {entry.differences.map((difference) => (
                  <li key={difference.field}>
                    <strong>{difference.label}:</strong> {String(difference.right ?? '–')} statt{' '}
                    {String(difference.left ?? '–')}
                    {difference.critical && <Badge tone="warn">relevant</Badge>}
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
