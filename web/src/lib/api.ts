import { goto } from '$app/navigation';

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

const messageOf = (body: unknown, fallback: string): string => {
  if (body && typeof body === 'object') {
    const b = body as { message?: unknown; detail?: unknown };
    if (typeof b.message === 'string') return b.message;
    if (Array.isArray(b.detail)) return b.detail.map((d: { msg?: string }) => d.msg).join('; ');
    if (typeof b.detail === 'string') return b.detail;
  }
  return fallback;
};

export async function api<T = unknown>(path: string, init: { method?: string; body?: unknown } = {}): Promise<T> {
  const res = await fetch(`/api${path}`, {
    method: init.method ?? (init.body === undefined ? 'GET' : 'POST'),
    headers: init.body === undefined ? {} : { 'Content-Type': 'application/json' },
    body: init.body === undefined ? undefined : JSON.stringify(init.body),
    credentials: 'same-origin',
  });
  const body = res.headers.get('content-type')?.includes('json') ? await res.json() : null;
  if (!res.ok) {
    if (res.status === 401 && !path.startsWith('/auth/')) await goto('/login');
    throw new ApiError(res.status, messageOf(body, res.statusText));
  }
  return body as T;
}

export const qs = (params: Record<string, string | number | boolean | null | undefined>) => {
  const p = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) if (v !== undefined && v !== null && v !== '') p.set(k, String(v));
  const s = p.toString();
  return s ? `?${s}` : '';
};

export const thumbUrl = (id: string, size: 'thumbnail' | 'preview' = 'thumbnail') =>
  `/api/assets/${id}/thumbnail?size=${size}`;

export type User = { id: string; name: string; email: string; isAdmin: boolean };

export type ServerInfo = {
  version: string;
  immichVersion: string | null;
  immichUrl: string;
  defaultTimeZone: string;
  claude: { configured: boolean; models: string[]; defaultModel: string; prices: Record<string, [number, number]> };
  ollama: { configured: boolean; reachable?: boolean; installed?: boolean; model?: string; error?: string };
  issueLabels: Record<string, string>;
  decisionReasons: { code: string; label: string; actions: DecisionAction[] }[];
};

export type DecisionAction = 'applied' | 'rejected' | 'reverted' | 'manual';
export type Reason = { reason: string | null; note: string | null };

export type DecisionRow = { key: string; accepted: number; rejected: number; auto: number; manual: number; rate: number | null };
export type DecisionStats = {
  total: number;
  bySource: DecisionRow[];
  byCamera: DecisionRow[];
  byIssue: DecisionRow[];
  byPattern: DecisionRow[];
  reasons: { action: string; reason: string; label: string; count: number }[];
};

export type Job = {
  id: string;
  kind: string;
  status: 'running' | 'done' | 'failed' | 'cancelled';
  phase: string | null;
  progress: number | null;
  total: number | null;
  message: string | null;
  stats: Record<string, unknown>;
  started_at: string;
  finished_at: string | null;
};

export type Summary = {
  total: number;
  categories: Record<string, number>;
  issues: Record<string, number>;
  suggestions: Record<string, number>;
  pendingBySource: Record<string, number>;
  unresolved: number;
  lastScan: Job | null;
  claudeSpentUsd: number;
};

export type AssetView = {
  id: string;
  fileName: string;
  path: string;
  type: 'IMAGE' | 'VIDEO';
  localDateTime: string | null;
  timeZone: string | null;
  make: string | null;
  model: string | null;
  city: string | null;
  country: string | null;
  issues: string[];
  category: string;
};

export type Suggestion = {
  id: number;
  asset_id: string;
  source: string;
  proposed: string;
  precision: string;
  range_start: string | null;
  range_end: string | null;
  confidence: number;
  explanation: string;
  status: string;
  previous_date: string | null;
  created_at: string;
  applied_at: string | null;
  asset: AssetView;
};

export type AssetDetail = AssetView & {
  people: { name: string; birthDate: string | null }[];
  fileCreatedAt: string;
  uploadedAt: string;
  suggestions: Omit<Suggestion, 'asset'>[];
  immichLink: string;
};

export type Page<T> = { items: T[]; total: number; page: number; size: number };

export type Settings = {
  auto_apply: boolean;
  claude_model: string | null;
  claude_budget_usd: number;
  ollama_enabled: boolean;
  ollama_max_per_scan: number;
};

export type Estimate = {
  model: string;
  count: number;
  per_image_usd: number;
  total_usd: number;
  max_per_image_usd: number;
  budget_usd: number;
  configured: boolean;
  fits_budget: boolean;
};
