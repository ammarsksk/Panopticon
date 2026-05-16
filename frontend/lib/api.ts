const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

export type Recommendation = {
  id: number;
  project_path: string;
  source_type: string;
  source_id: string;
  channel: string;
  message: string;
  title: string;
  summary: string;
  gemini_analysis: string;
  evidence: string[];
  next_actions: string[];
  origin: "demo" | "gitlab";
  status: string;
  created_at: string;
};

export type SlackStatus = {
  configured: boolean;
  mode: "dry_run" | "live";
  last_status: string;
  last_error: string;
  last_checked_at: string | null;
};

export type DashboardSummary = {
  active_risks: number;
  failed_pipelines: number;
  blocked_merge_requests: number;
  open_incidents: number;
  latest_recommendations: Recommendation[];
  slack_status: SlackStatus;
};

export type Risk = {
  id: number;
  project_path: string;
  merge_request_iid: string;
  deployment_ref: string;
  score: number;
  level: string;
  summary: string;
  reasons: string[];
  recommendations: string[];
  created_at: string;
};

export type PipelineInsight = {
  id: number;
  project_path: string;
  pipeline_id: string;
  status: string;
  likely_cause: string;
  evidence: string[];
  recommendations: string[];
  created_at: string;
};

export type MergeRequestSignal = {
  id: number;
  project_path: string;
  merge_request_iid: string;
  title: string;
  bottleneck_level: string;
  summary: string;
  age_hours: number;
};

export type Incident = {
  id: number;
  project_path: string;
  title: string;
  severity: string;
  probable_root_cause: string;
  timeline: { time: string; event: string }[];
  recommendations: string[];
};

export type MemoryRecord = {
  id: number;
  project_path: string;
  memory_type: string;
  signature: string;
  summary: string;
  evidence: string[];
  remediation: string[];
};

async function get<T>(path: string): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, { cache: "no-store" });
  if (!response.ok) {
    throw new Error(`Failed to load ${path}`);
  }
  return response.json();
}

export async function getDashboardData() {
  const [summary, risks, pipelines, mergeRequests, incidents, memory] = await Promise.all([
    get<DashboardSummary>("/api/dashboard/summary"),
    get<Risk[]>("/api/risks"),
    get<PipelineInsight[]>("/api/pipelines"),
    get<MergeRequestSignal[]>("/api/merge-requests"),
    get<Incident[]>("/api/incidents"),
    get<MemoryRecord[]>("/api/memory")
  ]);

  return { summary, risks, pipelines, mergeRequests, incidents, memory };
}
