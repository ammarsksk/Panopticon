import Link from "next/link";
import { Activity, AlertTriangle, CheckCircle2, GitPullRequest, History, RadioTower, Send, ShieldAlert } from "lucide-react";
import { getDashboardData, Recommendation } from "@/lib/api";

function Metric({ label, value, tone }: { label: string; value: number; tone: "neutral" | "warn" | "critical" }) {
  const color = tone === "critical" ? "text-red-700" : tone === "warn" ? "text-amber-700" : "text-slate-950";
  return (
    <div className="border border-slate-200 bg-white p-4">
      <div className="text-xs font-medium uppercase text-slate-500">{label}</div>
      <div className={`mt-2 text-3xl font-semibold ${color}`}>{value}</div>
    </div>
  );
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

function Badge({ label, tone = "neutral" }: { label: string; tone?: "neutral" | "good" | "warn" | "critical" }) {
  const styles = {
    neutral: "border-slate-200 bg-slate-50 text-slate-600",
    good: "border-emerald-200 bg-emerald-50 text-emerald-700",
    warn: "border-amber-200 bg-amber-50 text-amber-700",
    critical: "border-red-200 bg-red-50 text-red-700"
  };
  return <span className={`border px-2 py-1 text-xs font-semibold uppercase ${styles[tone]}`}>{label}</span>;
}

function statusTone(status: string): "neutral" | "good" | "warn" | "critical" {
  if (status === "sent") return "good";
  if (status === "dry_run" || status === "queued") return "warn";
  if (status === "failed") return "critical";
  return "neutral";
}

function severityTone(severity: string): "neutral" | "good" | "warn" | "critical" {
  if (severity === "critical" || severity === "high") return "critical";
  if (severity === "medium") return "warn";
  if (severity === "low") return "good";
  return "neutral";
}

function uniqueBy<T>(items: T[], keyFor: (item: T) => string): T[] {
  const seen = new Set<string>();
  return items.filter((item) => {
    const key = keyFor(item);
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

function ActionCard({ recommendation }: { recommendation: Recommendation }) {
  const evidence = recommendation.evidence ?? [];
  const nextActions = recommendation.next_actions ?? [];
  const origin = recommendation.origin ?? "gitlab";
  const status = recommendation.status ?? "queued";
  const severity = recommendation.severity ?? "info";
  const confidence = Math.round((recommendation.confidence ?? 0) * 100);

  return (
    <article className="flex min-h-[260px] flex-col border border-slate-200 bg-white p-4">
      <div className="flex items-start justify-between gap-3">
        <div className="space-y-2">
          <div className="flex flex-wrap gap-2">
            <Badge label={recommendation.channel} />
            <Badge label={status} tone={statusTone(status)} />
            <Badge label={severity} tone={severityTone(severity)} />
            <Badge label={origin} tone={origin === "gitlab" ? "good" : "neutral"} />
          </div>
          <h3 className="text-base font-semibold text-slate-950">{recommendation.title || "Operational recommendation"}</h3>
        </div>
        <div className="text-xs uppercase text-slate-500">{recommendation.source_type}</div>
      </div>

      <p className="mt-3 text-sm leading-6 text-slate-700">{recommendation.summary || recommendation.message || "No summary available."}</p>

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

      {recommendation.gemini_analysis ? (
        <div className="mt-4 border-l-2 border-teal-600 pl-3">
          <div className="text-xs font-semibold uppercase text-teal-700">Vertex Gemini Analysis</div>
          <p className="mt-1 whitespace-pre-line text-sm leading-6 text-slate-700">{recommendation.gemini_analysis}</p>
        </div>
      ) : null}

      <div className="mt-4 grid gap-3 md:grid-cols-2">
        <DetailList title="Evidence" items={evidence} />
        <DetailList title="Next Actions" items={nextActions} />
      </div>
    </article>
  );
}

function DetailList({ title, items }: { title: string; items: string[] }) {
  return (
    <div>
      <div className="text-xs font-semibold uppercase text-slate-500">{title}</div>
      {items.length ? (
        <ul className="mt-2 space-y-1 text-sm text-slate-700">
          {items.slice(0, 3).map((item) => (
            <li key={item}>{item}</li>
          ))}
        </ul>
      ) : (
        <p className="mt-2 text-sm text-slate-500">None recorded.</p>
      )}
    </div>
  );
}

export default async function Home() {
  const { summary, risks, pipelines, mergeRequests, incidents, memory } = await getDashboardData();
  const visibleRisks = uniqueBy(risks, (risk) => `${risk.project_path}:${risk.merge_request_iid}:${risk.score}`);
  const visibleRecommendations = summary.latest_recommendations;
  const slackStatus = summary.slack_status ?? {
    configured: false,
    webhook_configured: false,
    bot_token_configured: false,
    signing_secret_configured: false,
    default_channel_configured: false,
    default_channel: "",
    mode: "dry_run",
    last_status: "unknown",
    last_error: "",
    last_checked_at: null
  };

  return (
    <main className="min-h-screen bg-slate-50 text-slate-950">
      <header className="border-b border-slate-200 bg-white">
        <div className="mx-auto flex max-w-7xl items-center justify-between px-6 py-5">
          <div>
            <h1 className="text-2xl font-semibold">Panopticon</h1>
            <p className="mt-1 text-sm text-slate-600">Autonomous GitLab operations intelligence</p>
          </div>
          <div className="flex items-center gap-2 text-sm font-medium text-teal-700">
            <RadioTower size={18} />
            Live Operations Console
            <Link href="/projects" className="ml-3 border border-teal-700 px-3 py-2 text-sm font-semibold text-teal-700">
              Projects
            </Link>
            <Link href="/actions" className="border border-teal-700 px-3 py-2 text-sm font-semibold text-teal-700">
              Actions
            </Link>
            <Link href="/fix-plans" className="border border-teal-700 px-3 py-2 text-sm font-semibold text-teal-700">
              Fix Plans
            </Link>
            <Link href="/observability" className="border border-teal-700 px-3 py-2 text-sm font-semibold text-teal-700">
              Observability
            </Link>
            <Link href="/chat" className="border border-teal-700 px-3 py-2 text-sm font-semibold text-teal-700">
              Chat
            </Link>
          </div>
        </div>
      </header>

      <div className="mx-auto max-w-7xl px-6 py-6">
        <div className="grid gap-3 md:grid-cols-4">
          <Metric label="Active high risks" value={summary.active_risks} tone="critical" />
          <Metric label="Failed pipelines" value={summary.failed_pipelines} tone="warn" />
          <Metric label="Blocked MRs" value={summary.blocked_merge_requests} tone="warn" />
          <Metric label="Open incidents" value={summary.open_incidents} tone="critical" />
        </div>

        <Section title="Integration Status" icon={<CheckCircle2 className="text-teal-700" size={20} />}>
          <div className="grid gap-3 md:grid-cols-3 lg:grid-cols-6">
            <div className="border border-slate-200 bg-white p-4">
              <div className="text-xs font-semibold uppercase text-slate-500">Slack Webhook</div>
              <div className="mt-2">
                <Badge label={slackStatus.webhook_configured ? "configured" : "missing"} tone={slackStatus.webhook_configured ? "good" : "critical"} />
              </div>
            </div>
            <div className="border border-slate-200 bg-white p-4">
              <div className="text-xs font-semibold uppercase text-slate-500">Slack App</div>
              <div className="mt-2">
                <Badge label={slackStatus.signing_secret_configured ? "verified" : "missing secret"} tone={slackStatus.signing_secret_configured ? "good" : "critical"} />
              </div>
            </div>
            <div className="border border-slate-200 bg-white p-4">
              <div className="text-xs font-semibold uppercase text-slate-500">Bot Token</div>
              <div className="mt-2">
                <Badge label={slackStatus.bot_token_configured ? "configured" : "missing"} tone={slackStatus.bot_token_configured ? "good" : "warn"} />
              </div>
            </div>
            <div className="border border-slate-200 bg-white p-4">
              <div className="text-xs font-semibold uppercase text-slate-500">Default Channel</div>
              <div className="mt-2">
                <Badge label={slackStatus.default_channel_configured ? slackStatus.default_channel : "missing"} tone={slackStatus.default_channel_configured ? "good" : "warn"} />
              </div>
            </div>
            <div className="border border-slate-200 bg-white p-4">
              <div className="text-xs font-semibold uppercase text-slate-500">Action Mode</div>
              <div className="mt-2">
                <Badge label={slackStatus.mode} tone={slackStatus.mode === "dry_run" ? "warn" : "good"} />
              </div>
            </div>
            <div className="border border-slate-200 bg-white p-4">
              <div className="text-xs font-semibold uppercase text-slate-500">Last Slack Dispatch</div>
              <p className="mt-2 text-sm text-slate-700">{slackStatus.last_status}</p>
              {slackStatus.last_error ? <p className="mt-1 text-sm text-red-700">{slackStatus.last_error}</p> : null}
            </div>
          </div>
        </Section>

        <Section title="Deployment Risk Center" icon={<ShieldAlert className="text-red-700" size={20} />}>
          {visibleRisks.length ? (
            <div className="grid gap-3 lg:grid-cols-2">
              {visibleRisks.slice(0, 4).map((risk) => (
                <article key={risk.id} className="border border-slate-200 bg-white p-4">
                  <div className="flex items-center justify-between gap-3">
                    <div className="font-medium">{risk.project_path}</div>
                    <Badge label={`${risk.score}/100 ${risk.level}`} tone="critical" />
                  </div>
                  <p className="mt-2 text-sm text-slate-700">{risk.summary}</p>
                  <DetailList title="Evidence" items={risk.reasons} />
                </article>
              ))}
            </div>
          ) : (
            <EmptyState label="No deployment risks recorded yet." />
          )}
        </Section>

        <div className="grid gap-6 lg:grid-cols-2">
          <Section title="Pipeline Intelligence Feed" icon={<Activity className="text-amber-700" size={20} />}>
            {pipelines.length ? (
              <div className="space-y-3">
                {pipelines.slice(0, 5).map((pipeline) => (
                  <article key={pipeline.id} className="border border-slate-200 bg-white p-4">
                    <div className="flex items-center justify-between">
                      <div className="font-medium">{pipeline.project_path}</div>
                      <Badge label={pipeline.status} tone={pipeline.status === "failed" ? "critical" : "neutral"} />
                    </div>
                    <p className="mt-2 text-sm text-slate-700">{pipeline.likely_cause}</p>
                  </article>
                ))}
              </div>
            ) : (
              <EmptyState label="No pipeline failures recorded yet." />
            )}
          </Section>

          <Section title="Merge Request Coordination" icon={<GitPullRequest className="text-teal-700" size={20} />}>
            {mergeRequests.length ? (
              <div className="space-y-3">
                {mergeRequests.slice(0, 5).map((mr) => (
                  <article key={mr.id} className="border border-slate-200 bg-white p-4">
                    <div className="flex items-center justify-between gap-3">
                      <div className="font-medium">!{mr.merge_request_iid} {mr.title}</div>
                      <Badge label={mr.bottleneck_level} tone={mr.bottleneck_level === "blocked" ? "critical" : "neutral"} />
                    </div>
                    <p className="mt-2 text-sm text-slate-700">{mr.summary}</p>
                  </article>
                ))}
              </div>
            ) : (
              <EmptyState label="No merge request coordination signals recorded yet." />
            )}
          </Section>
        </div>

        <Section title="Incident Explorer" icon={<AlertTriangle className="text-red-700" size={20} />}>
          {incidents.length ? (
            <div className="grid gap-3 lg:grid-cols-2">
              {incidents.slice(0, 4).map((incident) => (
                <article key={incident.id} className="border border-slate-200 bg-white p-4">
                  <div className="font-medium">{incident.title}</div>
                  <p className="mt-2 text-sm text-slate-700">{incident.probable_root_cause}</p>
                  <DetailList title="Recommendations" items={incident.recommendations} />
                </article>
              ))}
            </div>
          ) : (
            <EmptyState label="No incidents recorded yet." />
          )}
        </Section>

        <Section title="Action Queue" icon={<Send className="text-teal-700" size={20} />}>
          {visibleRecommendations.length ? (
            <>
              <div className="mb-3 flex flex-wrap gap-2">
                <Badge label="ranked by severity and confidence" />
                <Badge label={`${visibleRecommendations.filter((item) => item.requires_approval).length} approval required`} tone="warn" />
                <Badge label={`${visibleRecommendations.filter((item) => item.can_execute).length} executable`} tone="good" />
              </div>
              <div className="grid gap-3 xl:grid-cols-2">
                {visibleRecommendations.map((recommendation) => (
                  <ActionCard key={recommendation.id} recommendation={recommendation} />
                ))}
              </div>
            </>
          ) : (
            <EmptyState label="No pending or dispatched actions recorded yet." />
          )}
        </Section>

        <Section title="Operational Memory" icon={<History className="text-slate-700" size={20} />}>
          {memory.length ? (
            <div className="grid gap-3 lg:grid-cols-3">
              {memory.slice(0, 6).map((record) => (
                <article key={record.id} className="border border-slate-200 bg-white p-4">
                  <Badge label={record.memory_type} />
                  <div className="mt-3 font-medium">{record.project_path}</div>
                  <p className="mt-2 text-sm text-slate-700">{record.summary}</p>
                </article>
              ))}
            </div>
          ) : (
            <EmptyState label="No operational memory recorded yet." />
          )}
        </Section>
      </div>
    </main>
  );
}
