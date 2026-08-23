import type { Meta, ScanOptions } from '../types';
import { Field } from './ui';

export interface OptionsState {
  profiles: string[];
  cookieModes: string[];
  referrers: string[];
  proxies: string[];
  rounds: number;
}

export function defaultOptions(meta: Meta | null): OptionsState {
  const profiles = (meta?.profiles ?? []).filter((p) => p.available).map((p) => p.key);
  return {
    profiles,
    cookieModes: ['necessary'],
    referrers: ['direct'],
    proxies: [],
    rounds: 1,
  };
}

export function toScanOptions(state: OptionsState): ScanOptions {
  return {
    profiles: state.profiles.length ? state.profiles : null,
    cookie_modes: state.cookieModes.length ? state.cookieModes : null,
    referrers: state.referrers.length ? state.referrers : null,
    proxies: state.proxies.length ? state.proxies : null,
    rounds: state.rounds,
  };
}

function toggle(list: string[], value: string): string[] {
  return list.includes(value) ? list.filter((item) => item !== value) : [...list, value];
}

export function ScanOptionsForm({
  meta,
  state,
  onChange,
}: {
  meta: Meta | null;
  state: OptionsState;
  onChange: (next: OptionsState) => void;
}) {
  if (!meta) return null;
  return (
    <div className="options-grid">
      <Field label="Browserprofile" hint="Jeder Test läuft in einem vollständig isolierten Profil.">
        <div className="chips">
          {meta.profiles.map((profile) => (
            <button
              key={profile.key}
              type="button"
              disabled={!profile.available}
              title={profile.description}
              className={`chip ${state.profiles.includes(profile.key) ? 'chip-on' : ''}`}
              onClick={() => onChange({ ...state, profiles: toggle(state.profiles, profile.key) })}
            >
              {profile.label}
            </button>
          ))}
        </div>
      </Field>

      <Field label="Cookie-Varianten" hint="A: nur notwendige · B: alle · C: Banner nicht bestätigen">
        <div className="chips">
          {meta.cookie_modes.map((mode) => (
            <button
              key={mode.key}
              type="button"
              className={`chip ${state.cookieModes.includes(mode.key) ? 'chip-on' : ''}`}
              onClick={() => onChange({ ...state, cookieModes: toggle(state.cookieModes, mode.key) })}
            >
              {mode.label}
            </button>
          ))}
        </div>
      </Field>

      <Field label="Einstiegspfad" hint="Optional: Direktaufruf, Google- oder Bing-Referrer.">
        <div className="chips">
          {meta.referrers.map((referrer) => (
            <button
              key={referrer}
              type="button"
              className={`chip ${state.referrers.includes(referrer) ? 'chip-on' : ''}`}
              onClick={() => onChange({ ...state, referrers: toggle(state.referrers, referrer) })}
            >
              {referrer === 'direct' ? 'Direkt' : referrer}
            </button>
          ))}
        </div>
      </Field>

      <Field
        label="Ausgangs-IP"
        hint={
          meta.proxy_labels.length
            ? 'Optional. Nur die Bezeichnung wird gespeichert, niemals Zugangsdaten.'
            : 'Keine Proxys konfiguriert – alle Tests laufen über die normale Internetverbindung.'
        }
      >
        <div className="chips">
          {meta.proxy_labels.length === 0 && <span className="muted small">direkt</span>}
          {meta.proxy_labels.map((label) => (
            <button
              key={label}
              type="button"
              className={`chip ${state.proxies.includes(label) ? 'chip-on' : ''}`}
              onClick={() => onChange({ ...state, proxies: toggle(state.proxies, label) })}
            >
              {label}
            </button>
          ))}
        </div>
      </Field>

      <Field label="Verifikationsrunden" hint="Mehrere Runden prüfen, ob ein Unterschied reproduzierbar ist.">
        <select
          value={state.rounds}
          onChange={(event) => onChange({ ...state, rounds: Number(event.target.value) })}
        >
          <option value={1}>1 Runde</option>
          <option value={2}>2 Runden</option>
          <option value={3}>3 Runden (empfohlen bei Unterschieden)</option>
        </select>
      </Field>
    </div>
  );
}
