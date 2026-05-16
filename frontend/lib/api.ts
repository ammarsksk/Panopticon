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
  severity: "critical" | "high" | "medium" | "low" | "info";
  confidence: number;
  action_type: string;
  can_execute: boolean;
  requires_approval: boolean;
  approval_state: string;
  rank_score: number;
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

export type GitLabProject = {
  id: number;
  gitlab_project_id: string;
  project_path: string;
  name: string;
  namespace: string;
  web_url: string;
  default_branch: string;
  visibility: string;
  description: string;
  last_activity_at: string | null;
  open_merge_requests_count: number;
  failed_pipelines_count: number;
  latest_pipeline_id: string;
  latest_pipeline_status: string;
  synced_at: string;
};

export type ProjectSyncRun = {
  id: number;
  provider: string;
  status: string;
  projects_seen: number;
  projects_updated: number;
  merge_requests_seen: number;
  pipelines_seen: number;
  jobs_seen: number;
  error: string;
  started_at: string;
  finished_at: string | null;
};

export type MergeRequestSnapshot = {
  id: number;
  gitlab_project_id: string;
  project_path: string;
  merge_request_iid: string;
  title: string;
  state: string;
  web_url: string;
  author_username: string;
  source_branch: string;
  target_branch: string;
  draft: boolean;
  created_at_gitlab: string | null;
  updated_at_gitlab: string | null;
  synced_at: string;
};

export type PipelineSnapshot = {
  id: number;
  gitlab_project_id: string;
  project_path: string;
  pipeline_id: string;
  status: string;
  ref: string;
  sha: string;
  web_url: string;
  created_at_gitlab: string | null;
  updated_at_gitlab: string | null;
  synced_at: string;
};

export type JobSnapshot = {
  id: number;
  gitlab_project_id: string;
  project_path: string;
  pipeline_id: string;
  job_id: string;
  name: string;
  stage: string;
  status: string;
  failure_reason: string;
  web_url: string;
  duration: number | null;
  created_at_gitlab: string | null;
  synced_at: string;
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
  status?: string;
  created_at?: string;
};

export type MemoryRecord = {
  id: number;
  project_path: string;
  memory_type: string;
  signature: string;
  summary: string;
  evidence: string[];
  remediation: string[];
  created_at?: string;
};

export type ActionDispatch = {
  id: number;
  recommendation_id: number | null;
  channel: string;
  status: string;
  target: string;
  request_payload: Record<string, unknown>;
  response_payload: Record<string, unknown>;
  error: string;
  created_at: string;
};

export type ProjectSummary = {
  project: GitLabProject;
  open_merge_requests: MergeRequestSnapshot[];
  latest_pipelines: PipelineSnapshot[];
  failed_jobs: JobSnapshot[];
  active_risks: Risk[];
  recent_incidents: Incident[];
  latest_recommendations: Recommendation[];
  recent_actions: ActionDispatch[];
  memory_records: MemoryRecord[];
};

async function get<T>(path: string): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, { cache: "no-store" });
  if (!response.ok) {
    throw new Error(`Failed to load ${path}`);
  }
  return response.json();
}

async function post<T>(path: string): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, { method: "POST", cache: "no-store" });
  if (!response.ok) {
    throw new Error(`Failed to post ${path}`);
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

export async function getProjectsData() {
  const [projects, syncRuns] = await Promise.all([
    get<GitLabProject[]>("/api/projects"),
    get<ProjectSyncRun[]>("/api/projects/sync-runs")
  ]);

  return { projects, syncRuns };
}

export async function syncGitLabProjects(limit = 50) {
  return post<ProjectSyncRun>(`/api/gitlab/projects/sync?limit=${limit}`);
}

export async function getProjectSummary(projectId: string | number) {
  return get<ProjectSummary>(`/api/projects/${projectId}/summary`);
}
