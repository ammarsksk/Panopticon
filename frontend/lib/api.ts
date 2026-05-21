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
  webhook_configured: boolean;
  bot_token_configured: boolean;
  signing_secret_configured: boolean;
  default_channel_configured: boolean;
  default_channel: string;
  mode: "dry_run" | "live";
  last_status: string;
  last_error: string;
  last_checked_at: string | null;
};

export type AiIntegrationStatus = {
  gemini_enabled: boolean;
  provider: "vertex_ai" | "gemini_api";
  model: string;
  google_cloud_project_configured: boolean;
  google_cloud_location: string;
  chat_mode: "vertex_gemini" | "deterministic_fallback";
  tool_layer: string;
  mcp_enabled: boolean;
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

export type ObservabilityEvent = {
  id: number;
  provider: string;
  event_uid: string;
  project_path: string;
  service_name: string;
  environment: string;
  severity: string;
  signal_type: string;
  title: string;
  message: string;
  metric_name: string;
  trace_id: string;
  alert_url: string;
  payload: Record<string, unknown>;
  observed_at: string;
  created_at: string;
};

export type IncidentCorrelation = {
  id: number;
  project_path: string;
  title: string;
  severity: string;
  status: string;
  summary: string;
  suspected_cause: string;
  confidence: number;
  timeline: Array<{ time: string; kind: string; title: string; detail: string; severity: string; id: number }>;
  related_observability_event_ids: number[];
  related_pipeline_ids: string[];
  related_risk_ids: number[];
  related_incident_ids: number[];
  recommendations: string[];
  created_at: string;
  updated_at: string;
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

export type AgentAction = {
  id: number;
  recommendation_id: number | null;
  project_path: string;
  action_type: string;
  channel: string;
  title: string;
  summary: string;
  status: string;
  requires_approval: boolean;
  payload_preview: Record<string, unknown>;
  execution_context: Record<string, unknown>;
  last_result: Record<string, unknown>;
  error: string;
  created_at: string;
  updated_at: string;
};

export type ChatThread = {
  id: number;
  project_id: number | null;
  project_path: string;
  title: string;
  created_at: string;
  updated_at: string;
};

export type ChatMessage = {
  id: number;
  thread_id: number;
  role: "user" | "assistant";
  content: string;
  citations: Array<{ type: string; id: number; label: string; summary: string }>;
  prepared_action_ids: number[];
  created_at: string;
};

export type ChatResponse = {
  thread: ChatThread;
  user_message: ChatMessage;
  assistant_message: ChatMessage;
  prepared_actions: AgentAction[];
};

export type FixPlan = {
  id: number;
  project_id: number | null;
  project_path: string;
  source_type: string;
  source_id: string;
  title: string;
  summary: string;
  status: string;
  requires_approval: boolean;
  fix_type: string;
  base_branch: string;
  branch_name: string;
  merge_request_iid: string;
  merge_request_url: string;
  plan_payload: {
    files?: Array<{ path: string; commit_action: string; purpose: string; content: string }>;
    manual_patch_suggestions?: Array<{ path: string; reason: string; suggestion: string }>;
    review_checklist?: string[];
    safety?: Record<string, unknown>;
  };
  last_result: Record<string, unknown>;
  error: string;
  created_at: string;
  updated_at: string;
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

async function postJson<T>(path: string, body: Record<string, unknown> = {}): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    method: "POST",
    cache: "no-store",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body)
  });
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

export async function getObservabilityData() {
  const [events, correlations, projects] = await Promise.all([
    get<ObservabilityEvent[]>("/api/observability/events"),
    get<IncidentCorrelation[]>("/api/observability/correlations"),
    get<GitLabProject[]>("/api/projects")
  ]);

  return { events, correlations, projects };
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

export async function getAgentActions() {
  return get<AgentAction[]>("/api/actions");
}

export async function proposeAgentActions() {
  return post<AgentAction[]>("/api/actions/propose-from-recommendations");
}

export async function approveAgentAction(actionId: number, reason = "") {
  return postJson<AgentAction>(`/api/actions/${actionId}/approve`, { actor: "local_user", reason });
}

export async function rejectAgentAction(actionId: number, reason = "") {
  return postJson<AgentAction>(`/api/actions/${actionId}/reject`, { actor: "local_user", reason });
}

export async function executeAgentAction(actionId: number) {
  return post<AgentAction>(`/api/actions/${actionId}/execute`);
}

export async function getChatThreads() {
  return get<ChatThread[]>("/api/chat/threads");
}

export async function getChatMessages(threadId: number) {
  return get<ChatMessage[]>(`/api/chat/threads/${threadId}`);
}

export async function getAiIntegrationStatus() {
  return get<AiIntegrationStatus>("/api/integrations/ai");
}

export async function sendChatMessage(message: string, projectId?: number, threadId?: number) {
  return postJson<ChatResponse>("/api/chat", {
    message,
    project_id: projectId || null,
    thread_id: threadId || null
  });
}

export async function getFixPlans() {
  return get<FixPlan[]>("/api/fix-plans");
}

export async function createFixPlan(body: {
  project_id?: number;
  project_path?: string;
  source_type?: string;
  source_id?: string;
  problem_statement?: string;
  fix_type?: string;
}) {
  return postJson<FixPlan>("/api/fix-plans", body);
}

export async function approveFixPlan(planId: number, reason = "") {
  return postJson<FixPlan>(`/api/fix-plans/${planId}/approve`, { actor: "local_user", reason });
}

export async function rejectFixPlan(planId: number, reason = "") {
  return postJson<FixPlan>(`/api/fix-plans/${planId}/reject`, { actor: "local_user", reason });
}

export async function createFixPlanBranch(planId: number) {
  return post<FixPlan>(`/api/fix-plans/${planId}/create-branch`);
}

export async function openFixPlanMergeRequest(planId: number) {
  return post<FixPlan>(`/api/fix-plans/${planId}/open-merge-request`);
}
