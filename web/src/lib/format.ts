export const CATEGORY_LABELS: Record<string, string> = {
  missing: 'Datum fehlt',
  wrong_clock: 'Falsche Kamera-Uhr',
  timezone: 'Zeitzone',
  scan: 'Scans',
  suspect: 'Verdächtig',
  ok: 'In Ordnung',
  fixed: 'Korrigiert',
  unscanned: 'Nicht geprüft',
};

export const SOURCE_LABELS: Record<string, string> = {
  gps: 'GPS-Zeit',
  exif_deep: 'Eingebettete Metadaten',
  filename: 'Dateiname',
  folder: 'Ordnername',
  duplicate: 'Duplikat',
  sequence: 'Bildfolge',
  similar: 'Ähnliche Bilder',
  ocr: 'Text im Bild',
  ollama: 'Lokale KI',
  claude: 'Claude',
  manual: 'Manuell',
  camera_shift: 'Kamera-Uhr',
};

export const STATUS_LABELS: Record<string, string> = {
  pending: 'Offen',
  applied: 'Übernommen',
  auto_applied: 'Automatisch übernommen',
  rejected: 'Abgelehnt',
  reverted: 'Rückgängig gemacht',
  superseded: 'Ersetzt',
};

export const PHASE_LABELS: Record<string, string> = {
  fetch: 'Bibliothek laden',
  duplicates: 'Duplikate',
  heuristics: 'Dateinamen & Metadaten',
  deep: 'Eingebettete Metadaten',
  local_context: 'Bildfolgen',
  remote_context: 'Texterkennung & ähnliche Bilder',
  local_ai: 'Lokale KI',
  combine: 'Vorschläge',
  auto_apply: 'Automatisch übernehmen',
  claude: 'Claude-Analyse',
};

const MONTHS = ['Jan.', 'Feb.', 'März', 'Apr.', 'Mai', 'Juni', 'Juli', 'Aug.', 'Sep.', 'Okt.', 'Nov.', 'Dez.'];
const pad = (n: number) => String(n).padStart(2, '0');

/** Parse the wall-clock part of an ISO string (ignores any offset – Immich dates are local). */
export function wallClock(iso: string | null | undefined): Date | null {
  const m = iso?.match(/^(\d{4})-(\d\d)-(\d\d)(?:[T ](\d\d):(\d\d)(?::(\d\d))?)?/);
  if (!m) return null;
  const [, y, mo, d, h = '0', mi = '0', s = '0'] = m;
  return new Date(Date.UTC(+y, +mo - 1, +d, +h, +mi, +s));
}

/** Format a date with as much detail as its precision justifies. */
export function formatDate(iso: string | null | undefined, precision = 'second'): string {
  const d = wallClock(iso);
  if (!d) return '–';
  const y = d.getUTCFullYear();
  const date = `${d.getUTCDate()}. ${MONTHS[d.getUTCMonth()]} ${y}`;
  const time = `${pad(d.getUTCHours())}:${pad(d.getUTCMinutes())}`;
  switch (precision) {
    case 'decade':
      return `${Math.floor(y / 10) * 10}er`;
    case 'year':
      return String(y);
    case 'month':
      return `${MONTHS[d.getUTCMonth()]} ${y}`;
    case 'day':
      return date;
    case 'hour':
      return `${date}, ca. ${pad(d.getUTCHours())} Uhr`;
    case 'minute':
      return `${date}, ${time}`;
    default:
      return `${date}, ${time}:${pad(d.getUTCSeconds())}`;
  }
}

/** Human readable difference between two wall-clock dates ("+3 J. 2 Mon.", "−2 Std."). */
export function formatShift(from: string | null | undefined, to: string | null | undefined): string {
  const a = wallClock(from);
  const b = wallClock(to);
  if (!a || !b) return '';
  const ms = b.getTime() - a.getTime();
  const sign = ms < 0 ? '−' : '+';
  const abs = Math.abs(ms) / 1000;
  const days = abs / 86400;
  if (days >= 365) {
    const years = Math.floor(days / 365.25);
    const months = Math.round((days - years * 365.25) / 30.44);
    return `${sign}${years} J.${months ? ` ${months} Mon.` : ''}`;
  }
  if (days >= 30) return `${sign}${Math.round(days / 30.44)} Mon.`;
  if (days >= 1) return `${sign}${Math.round(days)} Tg.`;
  if (abs >= 3600) return `${sign}${Math.round(abs / 3600)} Std.`;
  if (abs >= 60) return `${sign}${Math.round(abs / 60)} Min.`;
  return `${sign}${Math.round(abs)} Sek.`;
}

export const percent = (v: number) => `${Math.round(v * 100)} %`;
export const usd = (v: number) => (v < 0.01 && v > 0 ? `${v.toFixed(4)} $` : `${v.toFixed(2)} $`);

export function confidenceColor(v: number): 'success' | 'primary' | 'warning' | 'danger' {
  if (v >= 0.9) return 'success';
  if (v >= 0.75) return 'primary';
  if (v >= 0.5) return 'warning';
  return 'danger';
}

/** Value for <input type="datetime-local"> from an ISO string. */
export const toInputValue = (iso: string | null | undefined) => (iso ? iso.slice(0, 19) : '');

/** Format a real instant (UTC timestamp) in the browser's time zone. */
export const formatTimestamp = (iso: string | null | undefined) =>
  iso ? new Date(iso).toLocaleString('de-DE', { dateStyle: 'medium', timeStyle: 'short' }) : '–';
