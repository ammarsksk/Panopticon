import Link from "next/link";
import { Activity, AlertTriangle, ArrowLeft, ExternalLink, GitBranch, GitCommit, GitPullRequest, History, Send, ShieldAlert } from "lucide-react";
import { getProjectSummary, JobSnapshot, PipelineSnapshot, Recommendation, Risk } from "@/lib/api";

function Badge({ label, tone = "neutral" }: { label: string; tone?: "neutral" | "good" | "warn" | "critical" }) {
  const styles = {
    neutral: "border-slate-200 bg-slate-50 text-slate-600",
    good: "border-emerald-200 bg-emerald-50 text-emerald-700",
    warn: "border-amber-200 bg-amber-50 text-amber-700",
    critical: "border-red-200 bg-red-50 text-red-700"
  };
  return <span className={`border px-2 py-1 text-xs font-semibold uppercase ${styles[tone]}`}>{label || "unknown"}</span>;
}

function Section({ title, icon, children }: { title: string; icon: React.ReactNode; children: React.ReactNode }) {
  return (
    <section className="border-t border-slate-200 py-6">
      <div className="mb-4 flex items-center gap-2">
        {icon}
        <h2 className="text-lg font-semibold text-slate-950">{title}</h2>
      </div>
      {children}
    </section>
  );
}

function EmptyState({ label }: { label: string }) {
  return <div className="border border-dashed border-slate-300 bg-white p-5 text-sm text-slate-500">{label}</div>;
}

function statusTone(status: string): "neutral" | "good" | "warn" | "critical" {
  if (["success", "sent", "completed"].includes(status)) return "good";
  if (["failed", "critical"].includes(status)) return "critical";
  if (["running", "pending", "queued", "dry_run", "completed_with_errors"].includes(status)) return "warn";
  return "neutral";
}

function severityTone(severity: string): "neutral" | "good" | "warn" | "critical" {
  if (severity === "critical" || severity === "high") return "critical";
  if (severity === "medium") return "warn";
  if (severity === "low") return "good";
  return "neutral";
}

function Metric({ label, value, tone = "neutral" }: { label: string; value: number; tone?: "neutral" | "warn" | "critical" }) {
  const color = tone === "critical" ? "text-red-700" : tone === "warn" ? "text-amber-700" : "text-slate-950";
  return (
    <div className="border border-slate-200 bg-white p-4">
      <div className="text-xs font-medium uppercase text-slate-500">{label}</div>
      <div className={`mt-2 text-3xl font-semibold ${color}`}>{value}</div>
    </div>
  );
}

function PipelineCard({ pipeline }: { pipeline: PipelineSnapshot }) {
  return (
    <article className="border border-slate-200 bg-white p-4">
      <div className="flex items-start justify-between gap-3">
        <div>
          <div className="font-medium text-slate-950">Pipeline #{pipeline.pipeline_id}</div>
          <p className="mt-1 text-sm text-slate-600">{pipeline.ref || "unknown ref"}</p>
        </div>
        <Badge label={pipeline.status} tone={statusTone(pipeline.status)} />
      </div>
      <div className="mt-3 flex flex-wrap items-center gap-3 text-xs text-slate-500">
        <span>{pipeline.sha ? pipeline.sha.slice(0, 8) : "no sha"}</span>
        <span>Updated: {formatDate(pipeline.updated_at_gitlab)}</span>
        {pipeline.web_url ? (
          <a href={pipeline.web_url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 text-teal-700">
            GitLab
            <ExternalLink size={12} />
          </a>
        ) : null}
      </div>
    </article>
  );
}

function FailedJobCard({ job }: { job: JobSnapshot }) {
  return (
    <article className="border border-slate-200 bg-white p-4">
      <div className="flex items-start justify-between gap-3">
        <div>
          <div className="font-medium text-slate-950">{job.name}</div>
          <p className="mt-1 text-sm text-slate-600">{job.stage} stage</p>
        </div>
        <Badge label={job.failure_reason || job.status} tone="critical" />
      </div>
      <div className="mt-3 flex flex-wrap items-center gap-3 text-xs text-slate-500">
        <span>Pipeline #{job.pipeline_id}</span>
        {job.duration ? <span>{Math.round(job.duration)}s</span> : null}
        {job.web_url ? (
          <a href={job.web_url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 text-teal-700">
            Job
            <ExternalLink size={12} />
          </a>
        ) : null}
      </div>
    </article>
  );
}

function RiskCard({ risk }: { risk: Risk }) {
  return (
    <article className="border border-slate-200 bg-white p-4">
      <div className="flex items-center justify-between gap-3">
        <div className="font-medium text-slate-950">{risk.merge_request_iid ? `MR !${risk.merge_request_iid}` : risk.deployment_ref || "Deployment risk"}</div>
        <Badge label={`${risk.score}/100 ${risk.level}`} tone="critical" />
      </div>
      <p className="mt-2 text-sm leading-6 text-slate-700">{risk.summary}</p>
      <DetailList title="Evidence" items={risk.reasons} />
    </article>
  );
}

function RecommendationCard({ recommendation }: { recommendation: Recommendation }) {
  const confidence = Math.round((recommendation.confidence ?? 0) * 100);

  return (
    <article className="border border-slate-200 bg-white p-4">
      <div className="flex items-start justify-between gap-3">
        <div>
          <div className="flex flex-wrap gap-2">
            <Badge label={recommendation.channel} />
            <Badge label={recommendation.status} tone={statusTone(recommendation.status)} />
            <Badge label={recommendation.severity ?? "info"} tone={severityTone(recommendation.severity ?? "info")} />
          </div>
          <h3 className="mt-2 font-medium text-slate-950">{recommendation.title || "Operational recommendation"}</h3>
        </div>
        <div className="text-xs uppercase text-slate-500">{recommendation.source_type}</div>
      </div>
      <p className="mt-3 text-sm leading-6 text-slate-700">{recommendation.summary || recommendation.message}</p>
      <div className="mt-4 grid gap-2 text-xs text-slate-600 md:grid-cols-4">
        <div className="border border-slate-200 bg-slate-50 p-2">
          <div className="font-semibold uppercase text-slate-500">Action</div>
          <div className="mt-1">{recommendation.action_type ?? "dashboard_note"}</div>
        </div>
        <div className="border border-slate-200 bg-slate-50 p-2">
          <div className="font-semibold uppercase text-slate-500">Confidence</div>
          <div className="mt-1">{confidence}%</div>
        </div>
        <div className="border border-slate-200 bg-slate-50 p-2">
          <div className="font-semibold uppercase text-slate-500">Approval</div>
          <div className="mt-1">{recommendation.approval_state ?? "not_required"}</div>
        </div>
        <div className="border border-slate-200 bg-slate-50 p-2">
          <div className="font-semibold uppercase text-slate-500">Rank</div>
          <div className="mt-1">{Math.round(recommendation.rank_score ?? 0)}</div>
        </div>
      </div>
      <DetailList title="Next Actions" items={recommendation.next_actions ?? []} />
    </article>
  );
}

function DetailList({ title, items }: { title: string; items: string[] }) {
  return (
    <div className="mt-3">
      <div className="text-xs font-semibold uppercase text-slate-500">{title}</div>
      {items.length ? (
        <ul className="mt-2 space-y-1 text-sm text-slate-700">
          {items.slice(0, 4).map((item) => (
            <li key={item}>{item}</li>
          ))}
        </ul>
      ) : (
        <p className="mt-2 text-sm text-slate-500">None recorded.</p>
      )}
    </div>
  );
}

function formatDate(value: string | null | undefined) {
  if (!value) return "unknown";
  return new Intl.DateTimeFormat("en", {
    dateStyle: "medium",
    timeStyle: "short"
  }).format(new Date(value));
}

export default async function ProjectWorkspacePage({ params }: { params: Promise<{ projectId: string }> }) {
  const { projectId } = await params;
  const summary = await getProjectSummary(projectId);
  const project = summary.project;

  return (
    <main className="min-h-screen bg-slate-50 text-slate-950">
      <header className="border-b border-slate-200 bg-white">
        <div className="mx-auto max-w-7xl px-6 py-5">
          <Link href="/projects" className="mb-3 inline-flex items-center gap-2 text-sm font-medium text-teal-700">
            <ArrowLeft size={16} />
            Projects
          </Link>
          <div className="flex flex-wrap items-start justify-between gap-4">
            <div>
              <div className="flex flex-wrap items-center gap-2">
                <h1 className="text-2xl font-semibold">{project.name}</h1>
                <Badge label={project.visibility} />
              </div>
              <p className="mt-1 text-sm text-slate-600">{project.project_path}</p>
            </div>
            {project.web_url ? (
              <a href={project.web_url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 text-sm font-medium text-teal-700">
                Open in GitLab
                <ExternalLink size={14} />
              </a>
            ) : null}
          </div>
          <div className="mt-4 flex flex-wrap gap-3 text-xs text-slate-500">
            <span>Default branch: {project.default_branch || "unknown"}</span>
            <span>Last activity: {formatDate(project.last_activity_at)}</span>
            <span>Synced: {formatDate(project.synced_at)}</span>
          </div>
        </div>
      </header>

      <div className="mx-auto max-w-7xl px-6 py-6">
        <div className="grid gap-3 md:grid-cols-4">
          <Metric label="Open MRs" value={summary.open_merge_requests.length} />
          <Metric label="Failed jobs" value={summary.failed_jobs.length} tone={summary.failed_jobs.length ? "critical" : "neutral"} />
          <Metric label="Active risks" value={summary.active_risks.length} tone={summary.active_risks.length ? "critical" : "neutral"} />
          <Metric label="Actions" value={summary.recent_actions.length} tone={summary.recent_actions.length ? "warn" : "neutral"} />
        </div>

        <Section title="Open Merge Requests" icon={<GitPullRequest className="text-teal-700" size={20} />}>
          {summary.open_merge_requests.length ? (
            <div className="grid gap-3 lg:grid-cols-2">
              {summary.open_merge_requests.map((mr) => (
                <article key={mr.id} className="border border-slate-200 bg-white p-4">
                  <div className="flex items-start justify-between gap-3">
                    <div>
                      <div className="font-medium text-slate-950">!{mr.merge_request_iid} {mr.title}</div>
                      <p className="mt-1 text-sm text-slate-600">{mr.source_branch} {"->"} {mr.target_branch}</p>
                    </div>
                    <Badge label={mr.draft ? "draft" : mr.state} tone={mr.draft ? "warn" : "good"} />
                  </div>
                  <div className="mt-3 flex flex-wrap gap-3 text-xs text-slate-500">
                    <span>Author: {mr.author_username || "unknown"}</span>
                    <span>Updated: {formatDate(mr.updated_at_gitlab)}</span>
                    {mr.web_url ? (
                      <a href={mr.web_url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 text-teal-700">
                        MR
                        <ExternalLink size={12} />
                      </a>
                    ) : null}
                  </div>
                </article>
              ))}
            </div>
          ) : (
            <EmptyState label="No open merge requests synced for this project." />
          )}
        </Section>

        <div className="grid gap-6 lg:grid-cols-2">
          <Section title="Pipeline Health" icon={<Activity className="text-amber-700" size={20} />}>
            {summary.latest_pipelines.length ? (
              <div className="space-y-3">
                {summary.latest_pipelines.map((pipeline) => (
                  <PipelineCard key={pipeline.id} pipeline={pipeline} />
                ))}
              </div>
            ) : (
              <EmptyState label="No pipelines synced for this project yet." />
            )}
          </Section>

          <Section title="Failed Jobs" icon={<GitCommit className="text-red-700" size={20} />}>
            {summary.failed_jobs.length ? (
              <div className="space-y-3">
                {summary.failed_jobs.map((job) => (
                  <FailedJobCard key={job.id} job={job} />
                ))}
              </div>
            ) : (
              <EmptyState label="No failed jobs synced for this project." />
            )}
          </Section>
        </div>

        <Section title="Deployment Risk" icon={<ShieldAlert className="text-red-700" size={20} />}>
          {summary.active_risks.length ? (
            <div className="grid gap-3 lg:grid-cols-2">
              {summary.active_risks.map((risk) => (
                <RiskCard key={risk.id} risk={risk} />
              ))}
            </div>
          ) : (
            <EmptyState label="No active high-risk deployment records for this project." />
          )}
        </Section>

        <div className="grid gap-6 lg:grid-cols-2">
          <Section title="Recommendations" icon={<Send className="text-teal-700" size={20} />}>
            {summary.latest_recommendations.length ? (
              <>
                <div className="mb-3 flex flex-wrap gap-2">
                  <Badge label="ranked" />
                  <Badge label={`${summary.latest_recommendations.filter((item) => item.requires_approval).length} approval required`} tone="warn" />
                  <Badge label={`${summary.latest_recommendations.filter((item) => item.can_execute).length} executable`} tone="good" />
                </div>
                <div className="space-y-3">
                  {summary.latest_recommendations.map((recommendation) => (
                    <RecommendationCard key={recommendation.id} recommendation={recommendation} />
                  ))}
                </div>
              </>
            ) : (
              <EmptyState label="No recommendations generated for this project yet." />
            )}
          </Section>

          <Section title="Action History" icon={<History className="text-slate-700" size={20} />}>
            {summary.recent_actions.length ? (
              <div className="space-y-3">
                {summary.recent_actions.map((action) => (
                  <article key={action.id} className="border border-slate-200 bg-white p-4">
                    <div className="flex items-center justify-between gap-3">
                      <div className="font-medium text-slate-950">{action.channel}</div>
                      <Badge label={action.status} tone={statusTone(action.status)} />
                    </div>
                    <p className="mt-2 text-sm text-slate-600">{action.target || "No target recorded."}</p>
                    {action.error ? <p className="mt-2 text-sm text-red-700">{action.error}</p> : null}
                  </article>
                ))}
              </div>
            ) : (
              <EmptyState label="No action dispatches recorded for this project." />
            )}
          </Section>
        </div>

        <div className="grid gap-6 lg:grid-cols-2">
          <Section title="Incidents" icon={<AlertTriangle className="text-red-700" size={20} />}>
            {summary.recent_incidents.length ? (
              <div className="space-y-3">
                {summary.recent_incidents.map((incident) => (
                  <article key={incident.id} className="border border-slate-200 bg-white p-4">
                    <div className="flex items-center justify-between gap-3">
                      <div className="font-medium text-slate-950">{incident.title}</div>
                      <Badge label={incident.severity} tone={incident.severity === "critical" ? "critical" : "warn"} />
                    </div>
                    <p className="mt-2 text-sm leading-6 text-slate-700">{incident.probable_root_cause}</p>
                    <DetailList title="Recommendations" items={incident.recommendations} />
                  </article>
                ))}
              </div>
            ) : (
              <EmptyState label="No incidents recorded for this project." />
            )}
          </Section>

          <Section title="Operational Memory" icon={<History className="text-slate-700" size={20} />}>
            {summary.memory_records.length ? (
              <div className="space-y-3">
                {summary.memory_records.map((record) => (
                  <article key={record.id} className="border border-slate-200 bg-white p-4">
                    <Badge label={record.memory_type} />
                    <div className="mt-3 font-medium text-slate-950">{record.signature}</div>
                    <p className="mt-2 text-sm leading-6 text-slate-700">{record.summary}</p>
                    <DetailList title="Remediation" items={record.remediation} />
                  </article>
                ))}
              </div>
            ) : (
              <EmptyState label="No operational memory recorded for this project." />
            )}
          </Section>
        </div>
      </div>
    </main>
  );
}
