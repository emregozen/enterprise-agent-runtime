export type Health = {
  ok: boolean;
  llm_mode: string;
  run_backend: string;
};

export type DataSource = {
  id: string;
  name: string;
  dialect: string;
  description: string;
  dsn_env: string;
  allow_tables: string[];
  sensitivity: string;
  enabled: boolean;
  configured: boolean;
};

export type Schedule = {
  mode: string;
  cron: string | null;
  time_zone: string;
  next_run_at: string | null;
  paused: boolean;
  min_interval_seconds: number | null;
  max_interval_seconds: number | null;
  max_runs_per_day: number | null;
  window: string | null;
  concurrency: string;
};

export type Agent = {
  id: string;
  name: string;
  description: string;
  owner: string;
  status: string;
  current_version: number | null;
  goal: string;
  schedule: Schedule | null;
  created_at: string;
  updated_at: string;
  spec?: Record<string, unknown> | null;
  versions?: AgentVersion[];
};

export type AgentVersion = {
  version: number;
  status: string;
  created_at: string;
  spec: Record<string, unknown>;
};

export type Run = {
  id: string;
  agent_id: string;
  agent_name: string;
  spec_version: number;
  trigger: string;
  status: string;
  dry_run: boolean;
  job_name: string | null;
  summary: Record<string, unknown>;
  error: string | null;
  needs_review_reason: string | null;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  grand_total: number | null;
  anomaly_regions: string[];
};

export type RunStep = {
  ordinal: number;
  name: string;
  status: string;
  detail: Record<string, unknown>;
  created_at: string;
};

export type ToolCall = {
  tool: string;
  status: string;
  request: Record<string, unknown>;
  response: Record<string, unknown>;
  created_at: string;
};

export type Artifact = {
  id: string;
  name: string;
  media_type: string;
  sha256: string;
  size_bytes: number;
};

export type RunDetail = Run & {
  report_markdown: string | null;
  spec: Record<string, unknown>;
  steps: RunStep[];
  tool_calls: ToolCall[];
  artifacts: Artifact[];
  audit: { ts: string; actor: string; action: string; detail: Record<string, unknown> }[];
};

export type Draft = {
  spec: Record<string, unknown>;
  summary: {
    name: string;
    owner: string;
    version: number;
    goal: string;
    model: string;
    datasources: string[];
    tools: string[];
    schedule: Record<string, unknown> | null;
    verification: Record<string, unknown> | null;
    runtime: Record<string, unknown> | null;
  };
};
