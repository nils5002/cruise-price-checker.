const EUR = new Intl.NumberFormat('de-DE', { style: 'currency', currency: 'EUR', maximumFractionDigits: 2 });
const DATE = new Intl.DateTimeFormat('de-DE', { dateStyle: 'medium' });
const DATETIME = new Intl.DateTimeFormat('de-DE', { dateStyle: 'short', timeStyle: 'short' });

/**
 * Zeitstempel robust parsen: Werte ohne Zeitzonenangabe werden als UTC
 * gelesen (so liefert es das Backend), reine Datumsangaben bleiben lokal.
 */
function toDate(value: string): Date {
  if (value.length <= 10) return new Date(`${value}T00:00:00`);
  const hasZone = /(?:Z|[+-]\d{2}:?\d{2})$/.test(value);
  return new Date(hasZone ? value : `${value}Z`);
}

export function money(value: number | null | undefined, currency = 'EUR'): string {
  if (value === null || value === undefined) return '–';
  if (currency !== 'EUR') {
    return `${new Intl.NumberFormat('de-DE', { maximumFractionDigits: 2 }).format(value)} ${currency}`;
  }
  return EUR.format(value);
}

export function signedMoney(value: number | null | undefined): string {
  if (value === null || value === undefined) return '–';
  if (Math.abs(value) < 0.005) return '0 €';
  const formatted = money(Math.abs(value));
  return `${value > 0 ? '+' : '−'}${formatted}`;
}

export function percent(value: number | null | undefined): string {
  if (value === null || value === undefined) return '–';
  return `${new Intl.NumberFormat('de-DE', { maximumFractionDigits: 2 }).format(value)} %`;
}

export function isoDate(value: string | null | undefined): string {
  if (!value) return '–';
  const parsed = toDate(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return DATE.format(parsed);
}

export function dateTime(value: string | null | undefined): string {
  if (!value) return '–';
  const parsed = toDate(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return DATETIME.format(parsed);
}

export function relativeTime(value: string | null | undefined): string {
  if (!value) return '–';
  const parsed = toDate(value);
  if (Number.isNaN(parsed.getTime())) return value;
  const diffMinutes = Math.round((parsed.getTime() - Date.now()) / 60000);
  const absolute = Math.abs(diffMinutes);
  if (absolute < 60) return diffMinutes <= 0 ? `vor ${absolute} Min.` : `in ${absolute} Min.`;
  const hours = Math.round(absolute / 60);
  if (hours < 48) return diffMinutes <= 0 ? `vor ${hours} Std.` : `in ${hours} Std.`;
  const days = Math.round(hours / 24);
  return diffMinutes <= 0 ? `vor ${days} Tagen` : `in ${days} Tagen`;
}

export const STATUS_LABELS: Record<string, string> = {
  OK: 'OK',
  PARTIAL: 'Teilweise erfasst',
  PRICE_NOT_FOUND: 'Preis nicht ermittelbar',
  BLOCKED_CAPTCHA: 'BLOCKED / CAPTCHA',
  BOT_PROTECTION: 'BLOCKED / Bot-Schutz',
  TIMEOUT: 'Timeout',
  UNREACHABLE: 'Nicht erreichbar',
  SOLD_OUT: 'Reise ausverkauft',
  CABIN_SOLD_OUT: 'Kabine ausverkauft',
  SESSION_EXPIRED: 'Sitzung abgelaufen',
  PRICE_CHANGED_DURING_FLOW: 'Preis während Buchung geändert',
  SELECTOR_CHANGED: 'Seitenaufbau geändert',
  COOKIE_BANNER_CHANGED: 'Cookie-Banner geändert',
  SITE_ERROR: 'Website-Fehler',
  ERROR: 'Fehler',
  SKIPPED: 'Übersprungen',
  QUEUED: 'In Warteschlange',
  RUNNING: 'Läuft',
  DONE: 'Abgeschlossen',
  FAILED: 'Fehlgeschlagen',
  CANCELLED: 'Abgebrochen',
};

export const VERDICT_LABELS: Record<string, string> = {
  no_difference: 'Kein Unterschied',
  difference: 'Unterschied festgestellt',
  not_comparable: 'Angebote unterscheiden sich',
  insufficient_data: 'Keine belastbaren Daten',
};

export const COOKIE_LABELS: Record<string, string> = {
  necessary: 'nur notwendige',
  all: 'alle akzeptiert',
  none: 'Banner nicht bestätigt',
};

export function statusLabel(status: string | null | undefined): string {
  if (!status) return '–';
  return STATUS_LABELS[status] ?? status;
}

export function statusTone(status: string | null | undefined): 'ok' | 'warn' | 'bad' | 'muted' {
  switch (status) {
    case 'OK':
    case 'DONE':
      return 'ok';
    case 'PARTIAL':
    case 'PRICE_NOT_FOUND':
    case 'PRICE_CHANGED_DURING_FLOW':
    case 'RUNNING':
    case 'QUEUED':
      return 'warn';
    case undefined:
    case null:
      return 'muted';
    default:
      return 'bad';
  }
}
