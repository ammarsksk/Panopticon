import Link from "next/link";
import { Activity, ArrowLeft, BarChart3, CircleDot, GitPullRequest, ShieldAlert, TrendingUp } from "lucide-react";
import { getMetricsData, MetricSnapshot, ProjectHealth } from "@/lib/api";
import { RefreshMetricsButton } from "./RefreshMetricsButton";

function Badge({ label, tone = "neutral" }: { label: string; tone?: "neutral" | "good" | "warn" | "critical" }) {
  const styles = {
    neutral: "border-slate-200 bg-slate-50 text-slate-600",
    good: "border-emerald-200 bg-emerald-50 text-emerald-700",
    warn: "border-amber-200 bg-amber-50 text-amber-700",
    critical: "border-red-200 bg-red-50 text-red-700"
  };
  return <span className={`border px-2 py-1 text-xs font-semibold uppercase ${styles[tone]}`}>{label}</span>;
}

function healthTone(level: string): "neutral" | "good" | "warn" | "critical" {
  if (level === "healthy") return "good";
  if (level === "watch") return "warn";
  if (level === "at_risk" || level === "critical") return "critical";
  return "neutral";
}

function Metric({ label, value, detail, tone = "neutral" }: { label: string; value: string | number; detail?: string; tone?: "neutral" | "good" | "warn" | "critical" }) {
  const color = tone === "critical" ? "text-red-700" : tone === "warn" ? "text-amber-700" : tone === "good" ? "text-emerald-700" : "text-slate-950";
  return (
    <div className="border border-slate-200 bg-white p-4">
      <div className="text-xs font-medium uppercase text-slate-500">{label}</div>
      <div className={`mt-2 text-3xl font-semibold ${color}`}>{value}</div>
      {detail ? <div className="mt-1 text-sm text-slate-500">{detail}</div> : null}
    </div>
  );
}

function formatPercent(value: number) {
  return `${Math.round(value * 100)}%`;
}

function formatDate(value: string | null) {
  return value ? new Date(value).toLocaleString() : "unknown";
}

function ProjectRow({ project, rank }: { project: ProjectHealth; rank: number }) {
  return (
    <article className="border border-slate-200 bg-white p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="flex flex-wrap items-center gap-2">
            <Badge label={`#${rank}`} />
            <Badge label={project.health_level} tone={healthTone(project.health_level)} />
            <Badge label={`${project.health_score}/100`} tone={healthTone(project.health_level)} />
          </div>
          <h2 className="mt-3 text-lg font-semibold text-slate-950">{project.project_path}</h2>
          <p className="mt-1 text-sm text-slate-600">Last activity: {formatDate(project.last_activity_at)}</p>
        </div>
        <Link href={`/projects/${project.project_id}`} className="text-sm font-semibold text-teal-700">
          Open workspace
        </Link>
      </div>

      <div className="mt-4 grid gap-2 text-sm md:grid-cols-4">
        <div className="border border-slate-200 bg-slate-50 p-2">
          <div className="text-xs font-semibold uppercase text-slate-500">Pipeline Failures</div>
          <div className="mt-1">{project.failed_pipeline_count}/{project.pipeline_count} ({formatPercent(project.failed_pipeline_rate)})</div>
        </div>
        <div className="border border-slate-200 bg-slate-50 p-2">
          <div className="text-xs font-semibold uppercase text-slate-500">Risk</div>
          <div className="mt-1">{project.active_risks} active, max {project.max_risk_score}/100</div>
        </div>
        <div className="border border-slate-200 bg-slate-50 p-2">
          <div className="text-xs font-semibold uppercase text-slate-500">Incidents</div>
          <div className="mt-1">{project.open_incidents} open, {project.observability_alerts} alerts</div>
        </div>
        <div className="border border-slate-200 bg-slate-50 p-2">
          <div className="text-xs font-semibold uppercase text-slate-500">Actions</div>
          <div className="mt-1">{project.pending_actions} pending, {project.completed_actions} done</div>
        </div>
      </div>

      {project.top_reasons.length ? (
        <ul className="mt-4 space-y-1 text-sm leading-6 text-slate-700">
          {project.top_reasons.map((reason) => (
            <li key={reason}>- {reason}</li>
          ))}
        </ul>
      ) : (
        <p className="mt-4 text-sm text-slate-500">No major risk drivers recorded.</p>
      )}
    </article>
  );
}

function SnapshotList({ snapshots }: { snapshots: MetricSnapshot[] }) {
  const visible = snapshots.slice(0, 8);
  return (
    <div className="grid gap-3 lg:grid-cols-2">
      {visible.map((snapshot) => (
        <article key={snapshot.id} className="border border-slate-200 bg-white p-4">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div className="flex flex-wrap gap-2">
              <Badge label={snapshot.scope_type} />
              <Badge label={`${snapshot.health_score}/100`} tone={snapshot.health_score >= 85 ? "good" : snapshot.health_score >= 70 ? "warn" : "critical"} />
            </div>
            <div className="text-xs text-slate-500">{snapshot.snapshot_date}</div>
          </div>
          <div className="mt-3 font-semibold text-slate-950">{snapshot.project_path || "Organization"}</div>
          <p className="mt-1 text-sm text-slate-600">Updated {formatDate(snapshot.updated_at)}</p>
        </article>
      ))}
    </div>
  );
}

export default async function MetricsPage() {
  const { summary, projects, snapshots } = await getMetricsData();
  const atRisk = summary.projects_at_risk;
  const failedRate = formatPercent(summary.failed_pipeline_rate);

  return (
    <main className="min-h-screen bg-slate-50 text-slate-950">
      <header className="border-b border-slate-200 bg-white">
        <div className="mx-auto flex max-w-7xl items-center justify-between gap-4 px-6 py-5">
          <div>
            <Link href="/" className="mb-3 inline-flex items-center gap-2 text-sm font-medium text-teal-700">
              <ArrowLeft size={16} />
              Dashboard
            </Link>
            <div className="flex items-center gap-2">
              <BarChart3 className="text-teal-700" size={24} />
              <h1 className="text-2xl font-semibold">Engineering Health Metrics</h1>
            </div>
            <p className="mt-1 text-sm text-slate-600">Project health derived from GitLab delivery state, agent actions, incidents, and observability signals.</p>
          </div>
          <RefreshMetricsButton />
        </div>
      </header>

      <div className="mx-auto max-w-7xl px-6 py-6">
        <div className="grid gap-3 md:grid-cols-4">
          <Metric label="Average Health" value={`${summary.average_health_score}/100`} detail={summary.health_level} tone={healthTone(summary.health_level)} />
          <Metric label="Failed Pipeline Rate" value={failedRate} detail={`${summary.failed_pipelines}/${summary.total_pipelines} pipelines`} tone={summary.failed_pipeline_rate ? "warn" : "good"} />
          <Metric label="Projects At Risk" value={atRisk} detail={`${summary.project_count} total projects`} tone={atRisk ? "critical" : "good"} />
          <Metric label="Open Symptoms" value={summary.open_incidents + summary.observability_alerts} detail="incidents + alerts" tone={summary.open_incidents || summary.observability_alerts ? "critical" : "good"} />
        </div>

        <section className="border-t border-slate-200 py-6">
          <div className="mb-4 flex items-center gap-2">
            <ShieldAlert className="text-red-700" size={20} />
            <h2 className="text-lg font-semibold text-slate-950">Riskiest Projects</h2>
          </div>
          {summary.riskiest_projects.length ? (
            <div className="space-y-3">
              {summary.riskiest_projects.map((project, index) => (
                <ProjectRow key={project.project_path} project={project} rank={index + 1} />
              ))}
            </div>
          ) : (
            <div className="border border-dashed border-slate-300 bg-white p-6 text-sm text-slate-600">No project metrics yet. Sync GitLab projects or seed demo data.</div>
          )}
        </section>

        <section className="grid gap-6 border-t border-slate-200 py-6 lg:grid-cols-2">
          <div>
            <div className="mb-4 flex items-center gap-2">
              <TrendingUp className="text-emerald-700" size={20} />
              <h2 className="text-lg font-semibold text-slate-950">Healthiest Projects</h2>
            </div>
            <div className="space-y-3">
              {summary.healthiest_projects.map((project, index) => (
                <article key={project.project_path} className="border border-slate-200 bg-white p-4">
                  <div className="flex items-center justify-between gap-3">
                    <div>
                      <div className="font-semibold text-slate-950">{project.project_path}</div>
                      <div className="mt-1 text-sm text-slate-600">{project.top_reasons[0] || "No major risk drivers recorded."}</div>
                    </div>
                    <Badge label={`${project.health_score}/100`} tone={healthTone(project.health_level)} />
                  </div>
                </article>
              ))}
            </div>
          </div>

          <div>
            <div className="mb-4 flex items-center gap-2">
              <GitPullRequest className="text-teal-700" size={20} />
              <h2 className="text-lg font-semibold text-slate-950">Action Throughput</h2>
            </div>
            <div className="grid gap-3 sm:grid-cols-2">
              <Metric label="Pending Actions" value={summary.pending_actions} tone={summary.pending_actions ? "warn" : "good"} />
              <Metric label="Completed Actions" value={summary.completed_actions} tone="good" />
              <Metric label="Fix Plans" value={summary.fix_plans} />
              <Metric label="Active Risks" value={summary.active_risks} tone={summary.active_risks ? "critical" : "good"} />
            </div>
          </div>
        </section>

        <section className="border-t border-slate-200 py-6">
          <div className="mb-4 flex items-center gap-2">
            <Activity className="text-amber-700" size={20} />
            <h2 className="text-lg font-semibold text-slate-950">Daily Snapshots</h2>
          </div>
          {snapshots.length ? (
            <SnapshotList snapshots={snapshots} />
          ) : (
            <div className="border border-dashed border-slate-300 bg-white p-6 text-sm text-slate-600">
              No daily snapshots saved yet. Use Save Daily Snapshot to persist today&apos;s metrics.
            </div>
          )}
        </section>

        <section className="border-t border-slate-200 py-6">
          <div className="mb-4 flex items-center gap-2">
            <CircleDot className="text-slate-700" size={20} />
            <h2 className="text-lg font-semibold text-slate-950">All Project Scores</h2>
          </div>
          <div className="grid gap-3 lg:grid-cols-3">
            {projects.map((project) => (
              <article key={project.project_path} className="border border-slate-200 bg-white p-4">
                <div className="flex items-center justify-between gap-3">
                  <div className="min-w-0">
                    <div className="truncate font-semibold text-slate-950">{project.project_path}</div>
                    <div className="mt-1 text-sm text-slate-600">{project.failed_pipeline_count} failed pipeline(s), {project.open_incidents} incident(s)</div>
                  </div>
                  <Badge label={`${project.health_score}`} tone={healthTone(project.health_level)} />
                </div>
              </article>
            ))}
          </div>
        </section>
      </div>
    </main>
  );
}
