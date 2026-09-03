export type AgentRole = 'host' | 'client' | 'observer';

export interface SessionConfig {
  role: AgentRole;
  session: string;
  port: number;
  peer?: string;
  agentId?: string;
}

export interface HealthResponse {
  status: string;
  agent_id: string;
  role: string;
  session_id: string;
  port: number;
  advertised_url?: string;
  advertised_reachable_externally?: boolean;
  observability_ok?: boolean;
  last_message_age_s?: number | null;
  message_count?: number;
  peers?: Array<{
    agent_id: string;
    endpoint_url: string;
    topology_warning?: string | null;
    rtt_ms?: number;
    clock_skew_ms?: number;
  }>;
}

export interface HarnessLinks {
  antigravity?: string;
  codex?: string;
  opencode?: string;
  cursor?: string;
  notes?: string;
}

export interface RunbookItem {
  message_id: string;
  run_id?: number;
  title: string;
  steps: Array<{ role: string; instruction: string }>;
  status: string;
}

export interface RunbookState {
  pending: RunbookItem[];
  completed: RunbookItem[];
}

export interface FrictionHeatmap {
  taxonomies: string[];
  harnesses: string[];
  matrix: number[][];
  counts: Record<string, Record<string, number>>;
  cells: Record<string, Record<string, Array<{ id: string; status: string; severity: string }>>>;
  total_events: number;
  status_totals: Record<string, number>;
  csv_path?: string;
}

export interface AgentPeer {
  agent_id: string;
  role: string;
  endpoint_url: string;
  clock_offset_ms: number;
  topology_warning?: string | null;
  rtt_ms?: number;
}

export interface MessageEnvelope {
  message_id: string;
  sender_id: string;
  timestamp?: string;
  natural_language?: string;
  payload?: Record<string, unknown>;
  action?: string;
}

export interface EvidenceItem {
  relation: string;
  evidence_type: string;
  rationale: string;
}

export interface Hypothesis {
  id: string;
  title: string;
  description: string;
  status: string;
  evidence_graph?: EvidenceItem[];
}

export interface RunRecord {
  run_id: number;
  build?: string;
  outcome: string;
  host?: { last_received_packet?: number };
  client?: { last_sent_packet?: number };
  correlated_findings?: {
    discrepancies?: Array<{ code: string; description: string }>;
  };
}

export interface SessionSummary {
  session_id: string;
  peers_count: number;
  total_hypotheses: number;
  total_runs: number;
}

export function nodeBaseUrl(port: number): string {
  return `http://127.0.0.1:${port}`;
}

export async function fetchJson<T>(url: string, init?: RequestInit): Promise<T> {
  const res = await fetch(url, init);
  if (!res.ok) {
    throw new Error(`Request failed: ${res.status} ${res.statusText}`);
  }
  return res.json() as Promise<T>;
}

export function createApi(port: number) {
  const base = nodeBaseUrl(port);
  return {
    health: () => fetchJson<HealthResponse>(`${base}/health`),
    summary: () => fetchJson<SessionSummary>(`${base}/v1/a2a/summary`),
    peers: () => fetchJson<AgentPeer[]>(`${base}/v1/a2a/peers/detailed`),
    manifest: () => fetchJson<HarnessLinks>(`${base}/v1/a2a/session/manifest`),
    putManifest: (links: HarnessLinks) =>
      fetchJson<HarnessLinks>(`${base}/v1/a2a/session/manifest`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(links)
      }),
    runbook: (runId?: number) =>
      fetchJson<RunbookState>(`${base}/v1/a2a/runbook${runId != null ? `?run_id=${runId}` : ''}`),
    humanSignal: (payload: {
      run_id: number;
      signal: string;
      detail: string;
      human_role: string;
      ack_message_id?: string;
    }) =>
      fetchJson<unknown>(`${base}/v1/a2a/messages`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          sender_id: `human-${payload.human_role}`,
          action: 'human_signal',
          natural_language: payload.detail,
          payload,
          relay: true
        })
      }),
    messages: (limit = 200) => fetchJson<MessageEnvelope[]>(`${base}/v1/a2a/messages?limit=${limit}`),
    hypotheses: () => fetchJson<Hypothesis[]>(`${base}/v1/a2a/hypotheses`),
    runs: () => fetchJson<RunRecord[]>(`${base}/v1/a2a/runs`),
    transcript: () => fetch(`${base}/v1/a2a/transcript`).then((r) => r.text()),
    frictionHeatmap: () => fetchJson<FrictionHeatmap>(`${base}/v1/a2a/friction-heatmap`),
    sendChat: (senderId: string, text: string) =>
      fetchJson<unknown>(`${base}/v1/a2a/messages`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          sender_id: senderId,
          action: 'chat',
          natural_language: text,
          relay: true
        })
      }),
    eventsUrl: () => `${base}/v1/a2a/events`
  };
}

export type CrossLabApi = ReturnType<typeof createApi>;
