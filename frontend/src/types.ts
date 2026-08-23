export interface ProfileMeta {
  key: string;
  label: string;
  browser: string;
  device: string;
  platform: string;
  user_agent: string | null;
  viewport: { width: number; height: number };
  device_scale_factor: number;
  is_mobile: boolean;
  has_touch: boolean;
  session_type: string;
  persist_state: boolean;
  default_cookie_mode: string;
  description: string;
  available: boolean;
}

export interface Meta {
  app_name: string;
  version: string;
  environment: string;
  headless: boolean;
  profiles: ProfileMeta[];
  cookie_modes: { key: string; label: string }[];
  referrers: string[];
  unified_conditions: Record<string, unknown>;
  providers: { key: string; label: string; status: string; requires_browser?: boolean }[];
  proxy_labels: string[];
  schedule_intervals: string[];
  notification_channels: { key: string; label: string; configured: boolean }[];
  flights: { enabled: boolean; provider: string; preferred_airports: string[]; note: string };
  limits: Record<string, unknown>;
  allowed_domains: string[];
  api_key_required: boolean;
}

export interface ParsedUrl {
  provider: string;
  url: string;
  external_id: string | null;
  ship: string | null;
  departure_date: string | null;
  return_date: string | null;
  nights: number | null;
  origin: string | null;
  destination: string | null;
  cabin_type: string | null;
  cabin_category: string | null;
  adults: number | null;
  children: number | null;
  passenger_count: number | null;
  rate_code: string | null;
  price_code: string | null;
  flight_included: boolean | null;
  currency: string | null;
  raw_params: Record<string, string>;
}

export interface CruiseOverview {
  id: number;
  provider: string;
  title: string | null;
  url: string;
  ship: string | null;
  departure_date: string | null;
  return_date: string | null;
  nights: number | null;
  origin: string | null;
  destination: string | null;
  cabin_type: string | null;
  cabin_category: string | null;
  passenger_count: number | null;
  adults: number | null;
  children: number | null;
  flight_included: boolean | null;
  currency: string;
  monitoring_enabled: boolean;
  schedule_interval: string;
  best_price_ever: number | null;
  current_price: number | null;
  highest_price: number | null;
  change_since_previous: number | null;
  last_checked_at: string | null;
  next_check_at: string | null;
  last_scan_id: number | null;
  last_scan_status: string | null;
  last_verdict: string | null;
  history_points: number;
}

export interface Cruise extends Omit<CruiseOverview, 'best_price_ever' | 'current_price' | 'highest_price'> {
  route: string | null;
  rate_code: string | null;
  price_code: string | null;
  external_id: string | null;
  parsed_params: Record<string, unknown> | null;
  notes: string | null;
  created_at: string | null;
}

export interface AnalysisRow {
  key: string;
  profile: string;
  profile_label: string;
  device: string;
  browser: string;
  platform: string | null;
  cookie_mode: string;
  cookie_mode_applied: string | null;
  referrer: string;
  proxy_name: string | null;
  session_type: string;
  price: number | null;
  prices_by_round: Record<string, number | null>;
  rounds_with_price: number;
  price_stable: boolean;
  status: string;
  error: string | null;
  tariff: string | null;
  cabin_category: string | null;
  screenshot_path: string | null;
  identity_group: number | null;
  diff_to_cheapest: number | null;
  is_cheapest: boolean;
  is_most_expensive: boolean;
}

export interface Analysis {
  generated_at: string;
  currency: string;
  rounds_planned: number;
  rows: AnalysisRow[];
  warnings: string[];
  interpretation: string[];
  cause_hypotheses: {
    profile: string;
    profile_label: string;
    price: number | null;
    diff: number | null;
    possible_causes: string[];
    confidence: string;
  }[];
  identity_groups?: { id: number; members: string[]; identity: Record<string, unknown> }[];
  identity_differences?: {
    group_id: number;
    members: string[];
    reference_members: string[];
    summary: string;
    differences: { field: string; label: string; critical: boolean; left: unknown; right: unknown }[];
  }[];
  verdict: 'no_difference' | 'difference' | 'not_comparable' | 'insufficient_data';
  headline: string;
  comparable?: boolean;
  cheapest?: { profile: string; profile_label: string; price: number; device: string; session_type: string };
  most_expensive?: { profile: string; profile_label: string; price: number; device: string };
  lowest_price?: number | null;
  highest_price?: number | null;
  spread_abs?: number;
  spread_pct?: number;
  savings_text?: string;
  profiles_with_price?: number;
  reproducibility?: { rounds: number; status: string; text: string; unstable_profiles?: string[] };
}

export interface Scan {
  id: number;
  cruise_id: number;
  started_at: string | null;
  finished_at: string | null;
  status: string;
  trigger: string;
  rounds_planned: number;
  rounds_completed: number;
  profiles_requested: string[] | null;
  conditions: Record<string, unknown> | null;
  analysis: Analysis | null;
  error: string | null;
}

export interface ScanResult {
  id: number;
  round: number;
  profile: string;
  profile_label: string;
  device: string;
  browser: string;
  platform: string | null;
  cookie_mode: string;
  cookie_mode_applied: string | null;
  referrer: string | null;
  proxy_name: string | null;
  session_type: string;
  starting_price: number | null;
  price_per_person: number | null;
  cabin_price: number | null;
  total_price: number | null;
  service_fee: number | null;
  flight_price: number | null;
  transfer_price: number | null;
  drinks_package_price: number | null;
  extras_price: number | null;
  discount: number | null;
  final_price: number | null;
  promo_code: string | null;
  currency: string | null;
  tariff: string | null;
  cabin_category: string | null;
  cabin_type: string | null;
  offer_name: string | null;
  price_code: string | null;
  identity: Record<string, unknown> | null;
  price_details: Record<string, unknown> | null;
  conditions: Record<string, unknown> | null;
  final_url: string | null;
  page_type: string | null;
  deepest_step: string | null;
  screenshot_path: string | null;
  artifacts: { name: string; url?: string | null; screenshot?: string | null; html?: string | null }[] | null;
  status: string;
  error: string | null;
  attempts: number;
  duration_ms: number | null;
  created_at: string | null;
}

export interface ScanDetail extends Scan {
  results: ScanResult[];
}

export interface HistoryPoint {
  id: number;
  timestamp: string;
  lowest_price: number | null;
  highest_price: number | null;
  currency: string;
  lowest_profile: string | null;
  highest_profile: string | null;
  results_with_price: number;
  scan_id: number | null;
}

export interface Alert {
  id: number;
  cruise_id: number;
  enabled: boolean;
  channel: string;
  target: string | null;
  threshold_total: number | null;
  drop_percent: number | null;
  last_triggered_at: string | null;
  last_notified_price: number | null;
}

export interface CruiseDetailPayload {
  cruise: Cruise;
  overview: CruiseOverview;
  history: HistoryPoint[];
  scans: Scan[];
  latest_analysis: Analysis | null;
  latest_scan_id: number | null;
  alerts: Alert[];
}

export interface ScanOptions {
  profiles?: string[] | null;
  cookie_modes?: string[] | null;
  referrers?: string[] | null;
  proxies?: string[] | null;
  rounds: number;
}

export interface AdminStatus {
  version: string;
  environment: string;
  database_backend: string;
  playwright_available: boolean;
  headless: boolean;
  counts: Record<string, number>;
  result_status_counts: Record<string, number>;
  queue: { max_concurrent_scans: number; running: number[]; queued: number[] };
  scheduler: {
    enabled: boolean;
    running: boolean;
    check_every_minutes: number;
    supported_intervals: string[];
    timezone?: string;
    timezone_warning?: string | null;
    jobs: { id: string; next_run: string | null }[];
  };
  profiles: ProfileMeta[];
  providers: { key: string; label: string; status: string }[];
  proxy_profiles: { label: string; configured: boolean }[];
  notification_channels: { key: string; label: string; configured: boolean }[];
  flights: { enabled: boolean; provider: string; preferred_airports: string[]; note: string };
  storage: Record<string, { files: number; bytes: number }>;
  limits: Record<string, number>;
}

export interface AdminError {
  id: number;
  scan_id: number;
  profile: string;
  round: number;
  status: string;
  error: string;
  page_type: string | null;
  deepest_step: string | null;
  created_at: string | null;
  screenshot_path: string | null;
}
