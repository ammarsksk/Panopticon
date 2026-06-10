import Link from "next/link";
import { AlertCircle, ArrowLeft, ExternalLink, GitBranch, GitPullRequest, KeyRound, RefreshCw, Rows3 } from "lucide-react";
import { API_BASE, getProjectsData, GitLabProject, OAuthIntegrationStatus, ProjectSyncRun } from "@/lib/api";
import { redirectIfUnauthorized } from "../authRedirect";
import { SyncProjectsButton } from "./SyncProjectsButton";

function Badge({ label, tone = "neutral" }: { label: string; tone?: "neutral" | "good" | "warn" | "critical" }) {
  const styles = {
    neutral: "border-slate-200 bg-slate-50 text-slate-600",
    good: "border-emerald-200 bg-emerald-50 text-emerald-700",
    warn: "border-amber-200 bg-amber-50 text-amber-700",
    critical: "border-red-200 bg-red-50 text-red-700"
  };
  return <span className={`border px-2 py-1 text-xs font-semibold uppercase ${styles[tone]}`}>{label || "unknown"}</span>;
}

function pipelineTone(status: string): "neutral" | "good" | "warn" | "critical" {
  if (status === "success") return "good";
  if (status === "failed") return "critical";
  if (["running", "pending", "created"].includes(status)) return "warn";
  return "neutral";
}

function isDemoProject(project: GitLabProject) {
  return project.description.startsWith("Rich demo project") || project.project_path.startsWith("demo/");
}

function ProjectCard({ project }: { project: GitLabProject }) {
  const canOpenGitLab = Boolean(project.web_url) && !isDemoProject(project);

  return (
    <article className="border border-slate-200 bg-white p-4">
      <div className="flex items-start justify-between gap-4">
        <div>
          <div className="flex flex-wrap items-center gap-2">
            <h2 className="text-lg font-semibold text-slate-950">{project.name}</h2>
            <Badge label={project.visibility} />
            {isDemoProject(project) ? <Badge label="demo data" tone="warn" /> : null}
          </div>
          <p className="mt-1 text-sm text-slate-600">{project.project_path}</p>
        </div>
        <div className="flex items-center gap-3">
          <Link href={`/projects/${project.id}`} className="inline-flex items-center gap-1 text-sm font-medium text-teal-700">
            Workspace
            <Rows3 size={14} />
          </Link>
          {canOpenGitLab ? (
            <a href={project.web_url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 text-sm font-medium text-teal-700">
              GitLab
              <ExternalLink size={14} />
            </a>
          ) : null}
        </div>
      </div>

      {project.description ? <p className="mt-3 line-clamp-2 text-sm leading-6 text-slate-700">{project.description}</p> : null}

      <div className="mt-4 grid gap-3 md:grid-cols-3">
        <div className="border border-slate-200 bg-slate-50 p-3">
          <div className="flex items-center gap-2 text-xs font-semibold uppercase text-slate-500">
            <GitPullRequest size={14} />
            Open MRs
          </div>
          <div className="mt-2 text-2xl font-semibold text-slate-950">{project.open_merge_requests_count}</div>
        </div>
        <div className="border border-slate-200 bg-slate-50 p-3">
          <div className="flex items-center gap-2 text-xs font-semibold uppercase text-slate-500">
            <AlertCircle size={14} />
            Failed Pipelines
          </div>
          <div className="mt-2 text-2xl font-semibold text-red-700">{project.failed_pipelines_count}</div>
        </div>
        <div className="border border-slate-200 bg-slate-50 p-3">
          <div className="flex items-center gap-2 text-xs font-semibold uppercase text-slate-500">
            <GitBranch size={14} />
            Latest Pipeline
          </div>
          <div className="mt-2">
            <Badge label={project.latest_pipeline_status || "none"} tone={pipelineTone(project.latest_pipeline_status)} />
          </div>
        </div>
      </div>

      <div className="mt-4 flex flex-wrap items-center gap-3 text-xs text-slate-500">
        <span>Default branch: {project.default_branch || "unknown"}</span>
        <span>Last activity: {formatDate(project.last_activity_at)}</span>
        <span>Synced: {formatDate(project.synced_at)}</span>
      </div>
    </article>
  );
}

function SyncRunCard({ run }: { run: ProjectSyncRun }) {
  return (
    <article className="border border-slate-200 bg-white p-4">
      <div className="flex items-center justify-between gap-3">
        <div className="flex items-center gap-2 text-sm font-semibold text-slate-950">
          <RefreshCw size={16} />
          Sync #{run.id}
        </div>
        <Badge label={run.status} tone={run.status === "completed" ? "good" : run.status === "failed" ? "critical" : "warn"} />
      </div>
      <div className="mt-3 grid grid-cols-2 gap-3 text-sm text-slate-700">
        <div>Projects: {run.projects_updated}/{run.projects_seen}</div>
        <div>MRs: {run.merge_requests_seen}</div>
        <div>Pipelines: {run.pipelines_seen}</div>
        <div>Failed jobs: {run.jobs_seen}</div>
      </div>
      {run.error ? <p className="mt-3 text-sm text-red-700">{run.error}</p> : null}
      <p className="mt-3 text-xs text-slate-500">Finished: {formatDate(run.finished_at)}</p>
    </article>
  );
}

function GitLabIntegrationPanel({ integration }: { integration: OAuthIntegrationStatus }) {
  return (
    <section className="mb-6 border border-slate-200 bg-white p-4">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div>
          <div className="flex items-center gap-2 text-sm font-semibold uppercase text-slate-500">
            <KeyRound size={15} />
            GitLab OAuth
          </div>
          <h2 className="mt-2 text-lg font-semibold text-slate-950">
            {integration.connected ? `GitLab connected: ${integration.account_label || "GitLab user"}` : "Connect GitLab to sync real projects"}
          </h2>
          <p className="mt-1 text-sm leading-6 text-slate-600">
            {integration.connected
              ? "Project sync and GitLab write actions will use this workspace connection."
              : integration.configured
                ? "Connect your GitLab account so Panopticon can load accessible repositories, merge requests, pipelines, and failed jobs."
                : "Add the GitLab OAuth client id and secret in the backend environment before connecting."}
          </p>
        </div>
        <div className="flex items-center gap-3">
          <Badge label={integration.configured ? "oauth configured" : "oauth missing"} tone={integration.configured ? "good" : "warn"} />
          <Badge label={integration.connected ? "connected" : "not connected"} tone={integration.connected ? "good" : "warn"} />
          {!integration.connected ? (
            <a
              href={`${API_BASE}/api/integrations/gitlab/connect`}
              className="inline-flex items-center gap-2 border border-teal-700 bg-teal-700 px-4 py-2 text-sm font-semibold text-white transition hover:bg-teal-800"
            >
              <KeyRound size={16} />
              Connect GitLab
            </a>
          ) : null}
        </div>
      </div>
      {integration.scopes.length ? <p className="mt-3 text-xs text-slate-500">Scopes: {integration.scopes.join(", ")}</p> : null}
    </section>
  );
}

function formatDate(value: string | null) {
  if (!value) return "unknown";
  return new Intl.DateTimeFormat("en", {
    dateStyle: "medium",
    timeStyle: "short"
  }).format(new Date(value));
}

export default async function ProjectsPage() {
  let data;
  try {
    data = await getProjectsData();
  } catch (error) {
    redirectIfUnauthorized(error);
  }
  const { projects, syncRuns, gitlabIntegration } = data;
  const lastRun = syncRuns[0];

  return (
    <main className="min-h-screen bg-slate-50 text-slate-950">
      <header className="border-b border-slate-200 bg-white">
        <div className="mx-auto flex max-w-7xl items-center justify-between gap-4 px-6 py-5">
          <div>
            <Link href="/dashboard" className="mb-3 inline-flex items-center gap-2 text-sm font-medium text-teal-700">
              <ArrowLeft size={16} />
              Dashboard
            </Link>
            <h1 className="text-2xl font-semibold">GitLab Projects</h1>
            <p className="mt-1 text-sm text-slate-600">Synced repositories, active merge requests, and recent pipeline state.</p>
          </div>
          <SyncProjectsButton />
        </div>
      </header>

      <div className="mx-auto max-w-7xl px-6 py-6">
        <GitLabIntegrationPanel integration={gitlabIntegration} />

        {lastRun ? (
          <section className="mb-6">
            <div className="mb-3 text-xs font-semibold uppercase text-slate-500">Latest Sync</div>
            <SyncRunCard run={lastRun} />
          </section>
        ) : null}

        <section>
          <div className="mb-4 flex items-center justify-between gap-3">
            <h2 className="text-lg font-semibold text-slate-950">Repositories</h2>
            <div className="text-sm text-slate-500">{projects.length} project{projects.length === 1 ? "" : "s"}</div>
          </div>

          {projects.length ? (
            <div className="grid gap-3 xl:grid-cols-2">
              {projects.map((project) => (
                <ProjectCard key={project.id} project={project} />
              ))}
            </div>
          ) : (
            <div className="border border-dashed border-slate-300 bg-white p-6">
              <h3 className="font-semibold text-slate-950">No GitLab projects synced yet.</h3>
              <p className="mt-2 text-sm leading-6 text-slate-600">
                Use the sync button after `GITLAB_TOKEN` is configured. Panopticon will load accessible projects, open merge requests, latest pipelines, and failed jobs.
              </p>
            </div>
          )}
        </section>
      </div>
    </main>
  );
}
