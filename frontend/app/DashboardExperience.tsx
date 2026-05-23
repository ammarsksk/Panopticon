"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import {
  Activity,
  AlertTriangle,
  ArrowRight,
  Bot,
  CheckCircle2,
  ChevronDown,
  CircleDot,
  ClipboardCheck,
  GitBranch,
  GitPullRequest,
  History,
  LayoutDashboard,
  MessageSquare,
  RadioTower,
  Search,
  Send,
  ShieldAlert,
  Sparkles,
  Zap
} from "lucide-react";
import {
  API_BASE,
  DashboardSummary,
  Incident,
  MemoryRecord,
  MergeRequestSignal,
  PipelineInsight,
  Recommendation,
  Risk
} from "@/lib/api";

type DashboardData = {
  summary: DashboardSummary;
  risks: Risk[];
  pipelines: PipelineInsight[];
  mergeRequests: MergeRequestSignal[];
  incidents: Incident[];
  memory: MemoryRecord[];
};

type DashboardView = "overview" | "risk" | "pipeline" | "actions" | "incidents";
type Tone = "neutral" | "good" | "warn" | "critical";

const navItems = [
  { href: "/projects", label: "Projects", icon: GitBranch },
  { href: "/actions", label: "Actions", icon: ClipboardCheck },
  { href: "/fix-plans", label: "Fix Plans", icon: Bot },
  { href: "/observability", label: "Observability", icon: RadioTower },
  { href: "/metrics", label: "Metrics", icon: Activity },
  { href: "/chat", label: "Chat", icon: MessageSquare }
];

const views: Array<{ id: DashboardView; label: string; icon: typeof LayoutDashboard }> = [
  { id: "overview", label: "Overview", icon: LayoutDashboard },
  { id: "risk", label: "Risks", icon: ShieldAlert },
  { id: "pipeline", label: "Pipelines", icon: Activity },
  { id: "actions", label: "Actions", icon: Send },
  { id: "incidents", label: "Incidents", icon: AlertTriangle }
];

export function DashboardExperience({ data }: { data: DashboardData }) {
  const { summary, risks, pipelines, mergeRequests, incidents, memory } = data;
  const [view, setView] = useState<DashboardView>("overview");
  const [query, setQuery] = useState("");
  const [selectedActionId, setSelectedActionId] = useState(summary.latest_recommendations[0]?.id ?? 0);
  const [expandedRiskId, setExpandedRiskId] = useState<number | null>(risks[0]?.id ?? null);
  const [notice, setNotice] = useState("");

  const visibleRisks = useMemo(() => uniqueBy(risks, (risk) => `${risk.project_path}:${risk.merge_request_iid}:${risk.score}`), [risks]);
  const recommendations = summary.latest_recommendations ?? [];
  const selectedAction = recommendations.find((item) => item.id === selectedActionId) ?? recommendations[0];
  const filtered = useMemo(
    () =>
      filterDashboard({
        query,
        risks: visibleRisks,
        pipelines,
        mergeRequests,
        incidents,
        recommendations
      }),
    [query, visibleRisks, pipelines, mergeRequests, incidents, recommendations]
  );

  const slackStatus = summary.slack_status ?? {
    configured: false,
    webhook_configured: false,
    bot_token_configured: false,
    signing_secret_configured: false,
    default_channel_configured: false,
    default_channel: "",
    oauth_configured: false,
    oauth_connected: false,
    oauth_account_label: "",
    oauth_channel: "",
    mode: "dry_run",
    last_status: "unknown",
    last_error: "",
    last_checked_at: null
  };
  const pressure = summary.active_risks + summary.failed_pipelines + summary.blocked_merge_requests + summary.open_incidents;
  const headline = pressure > 8 ? "High operational pressure" : pressure > 3 ? "Focused review needed" : "Operations look controlled";
  const firstStep = firstNextStep(filtered.recommendations, filtered.risks, filtered.pipelines);

  function pulse(message: string) {
    setNotice(message);
    window.setTimeout(() => setNotice(""), 1600);
  }

  return (
    <main className="min-h-screen bg-[var(--background)] text-slate-950">
      {notice ? (
        <div className="fixed right-5 top-5 z-50 border border-teal-200 bg-white px-4 py-3 text-sm font-medium text-teal-800 shadow-sm">
          {notice}
        </div>
      ) : null}

      <header className="border-b border-slate-200 bg-white">
        <div className="mx-auto flex max-w-7xl flex-col gap-4 px-6 py-5 lg:flex-row lg:items-center lg:justify-between">
          <div>
            <div className="flex items-center gap-2 text-sm font-semibold text-teal-700">
              <RadioTower size={18} aria-hidden="true" />
              Live operations console
            </div>
            <h1 className="mt-2 text-2xl font-semibold tracking-normal">Panopticon</h1>
            <p className="mt-1 text-sm text-slate-600">GitLab delivery risk, incidents, actions, and AI recommendations in one place.</p>
          </div>

          <nav className="flex flex-wrap gap-2" aria-label="Dashboard navigation">
            {navItems.map((item) => (
              <Link
                key={item.href}
                href={item.href}
                className="group inline-flex items-center gap-2 border border-slate-300 bg-white px-3 py-2 text-sm font-semibold text-slate-700 transition duration-150 hover:-translate-y-0.5 hover:border-teal-500 hover:text-teal-700 focus:outline-none focus:ring-2 focus:ring-teal-500 focus:ring-offset-2 active:translate-y-0"
              >
                <item.icon size={16} aria-hidden="true" className="transition group-hover:scale-110" />
                {item.label}
              </Link>
            ))}
          </nav>
        </div>
      </header>

      <div className="mx-auto max-w-7xl px-6 py-6">
        <section className="border border-slate-200 bg-white p-5">
          <div className="grid gap-5 lg:grid-cols-[1.5fr_1fr]">
            <div>
              <div className="flex flex-wrap gap-2">
                <Badge label={slackStatus.mode === "dry_run" ? "Dry-run mode" : "Live actions"} tone={slackStatus.mode === "dry_run" ? "warn" : "good"} />
                <Badge label={slackStatus.webhook_configured || slackStatus.oauth_connected ? "Slack connected" : "Slack missing"} tone={slackStatus.webhook_configured || slackStatus.oauth_connected ? "good" : "critical"} />
                <Badge label={`${recommendations.filter((item) => item.requires_approval).length} approvals`} tone="warn" />
              </div>
              <h2 className="mt-4 text-2xl font-semibold">{headline}</h2>
              <p className="mt-2 max-w-3xl text-sm leading-6 text-slate-600">
                {firstStep}
              </p>
              <div className="mt-5 flex flex-wrap gap-2">
                <PrimaryLink href="/chat" icon={Sparkles} label="Ask Panopticon" />
                <SecondaryLink href="/actions" icon={ClipboardCheck} label="Review actions" />
                <SecondaryLink href="/metrics" icon={Activity} label="Open metrics" />
              </div>
            </div>

            <div className="border border-slate-200 bg-slate-50 p-4">
              <div className="mb-3 flex items-center justify-between">
                <div className="text-xs font-semibold uppercase text-slate-500">Command Summary</div>
                <CheckCircle2 size={17} className="text-teal-700" aria-hidden="true" />
              </div>
              <div className="grid grid-cols-2 gap-2">
                <MiniMetric label="High risks" value={summary.active_risks} tone="critical" />
                <MiniMetric label="Pipelines" value={summary.failed_pipelines} tone="warn" />
                <MiniMetric label="Blocked MRs" value={summary.blocked_merge_requests} tone="warn" />
                <MiniMetric label="Incidents" value={summary.open_incidents} tone="critical" />
              </div>
            </div>
          </div>
        </section>

        <section className="mt-4 grid gap-3 md:grid-cols-4">
          <MetricCard icon={ShieldAlert} label="Active high risks" value={summary.active_risks} tone="critical" hint="Deployment or MR risk above threshold" />
          <MetricCard icon={Activity} label="Failed pipelines" value={summary.failed_pipelines} tone="warn" hint="Recent GitLab pipeline failures" />
          <MetricCard icon={GitPullRequest} label="Blocked MRs" value={summary.blocked_merge_requests} tone="warn" hint="Merge requests needing coordination" />
          <MetricCard icon={AlertTriangle} label="Open incidents" value={summary.open_incidents} tone="critical" hint="Active incident records" />
        </section>

        <section className="mt-4 border border-slate-200 bg-white p-4">
          <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
            <div className="flex flex-wrap gap-2" role="tablist" aria-label="Dashboard views">
              {views.map((item) => (
                <button
                  key={item.id}
                  type="button"
                  role="tab"
                  aria-selected={view === item.id}
                  onClick={() => {
                    setView(item.id);
                    pulse(`Showing ${item.label.toLowerCase()}`);
                  }}
                  className={`inline-flex items-center gap-2 border px-3 py-2 text-sm font-semibold transition duration-150 focus:outline-none focus:ring-2 focus:ring-teal-500 focus:ring-offset-2 active:scale-[0.98] ${
                    view === item.id
                      ? "border-teal-700 bg-teal-700 text-white"
                      : "border-slate-300 bg-white text-slate-700 hover:-translate-y-0.5 hover:border-teal-500 hover:text-teal-700"
                  }`}
                >
                  <item.icon size={16} aria-hidden="true" />
                  {item.label}
                </button>
              ))}
            </div>

            <label className="relative block min-w-0 lg:w-80">
              <span className="sr-only">Search dashboard records</span>
              <Search className="pointer-events-none absolute left-3 top-2.5 text-slate-400" size={16} aria-hidden="true" />
              <input
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                placeholder="Search project, alert, action..."
                className="w-full border border-slate-300 bg-white py-2 pl-9 pr-3 text-sm text-slate-950 outline-none transition focus:border-teal-600 focus:ring-2 focus:ring-teal-500"
              />
            </label>
          </div>
        </section>

        <div className="mt-4 grid gap-4 xl:grid-cols-[1.45fr_0.85fr]">
          <section className="space-y-4">
            {view === "overview" ? (
              <OverviewPanel
                risks={filtered.risks}
                pipelines={filtered.pipelines}
                mergeRequests={filtered.mergeRequests}
                incidents={filtered.incidents}
                recommendations={filtered.recommendations}
                onSelectAction={(id) => {
                  setSelectedActionId(id);
                  pulse("Action details pinned");
                }}
              />
            ) : null}

            {view === "risk" ? (
              <RiskPanel risks={filtered.risks} expandedRiskId={expandedRiskId} setExpandedRiskId={setExpandedRiskId} pulse={pulse} />
            ) : null}

            {view === "pipeline" ? <PipelinePanel pipelines={filtered.pipelines} /> : null}

            {view === "actions" ? (
              <ActionsPanel
                recommendations={filtered.recommendations}
                selectedActionId={selectedAction?.id ?? 0}
                onSelect={(id) => {
                  setSelectedActionId(id);
                  pulse("Action details pinned");
                }}
              />
            ) : null}

            {view === "incidents" ? <IncidentPanel incidents={filtered.incidents} memory={memory} /> : null}
          </section>

          <aside className="space-y-4 xl:sticky xl:top-4 xl:self-start">
            <SelectedActionCard action={selectedAction} />
            <IntegrationPanel slackStatus={slackStatus} />
            <MemoryPanel memory={memory} />
          </aside>
        </div>
      </div>
    </main>
  );
}

function OverviewPanel({
  risks,
  pipelines,
  mergeRequests,
  incidents,
  recommendations,
  onSelectAction
}: {
  risks: Risk[];
  pipelines: PipelineInsight[];
  mergeRequests: MergeRequestSignal[];
  incidents: Incident[];
  recommendations: Recommendation[];
  onSelectAction: (id: number) => void;
}) {
  return (
    <>
      <Panel title="Priority Lane" icon={Zap} count={recommendations.length + risks.length + pipelines.length}>
        <div className="space-y-2">
          {recommendations.slice(0, 4).map((item) => (
            <button
              key={item.id}
              type="button"
              onClick={() => onSelectAction(item.id)}
              className="group w-full border border-slate-200 bg-white p-4 text-left transition duration-150 hover:-translate-y-0.5 hover:border-teal-500 hover:shadow-sm focus:outline-none focus:ring-2 focus:ring-teal-500 focus:ring-offset-2 active:translate-y-0"
            >
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div className="flex flex-wrap gap-2">
                  <Badge label={item.severity} tone={severityTone(item.severity)} />
                  <Badge label={item.channel} />
                  <Badge label={item.status} tone={statusTone(item.status)} />
                </div>
                <ArrowRight size={16} className="text-slate-400 transition group-hover:translate-x-1 group-hover:text-teal-700" aria-hidden="true" />
              </div>
              <div className="mt-3 font-semibold text-slate-950">{item.title || "Operational recommendation"}</div>
              <p className="mt-1 line-clamp-2 text-sm leading-6 text-slate-600">{item.summary || item.message}</p>
            </button>
          ))}
          {!recommendations.length ? <EmptyState label="No recommendations match the current search." /> : null}
        </div>
      </Panel>

      <div className="grid gap-4 lg:grid-cols-2">
        <CompactFeed title="Deployment Risk" icon={ShieldAlert} items={risks.slice(0, 4).map((risk) => ({ id: risk.id, title: risk.project_path, detail: risk.summary, badge: `${risk.score}/100 ${risk.level}`, tone: "critical" as Tone }))} />
        <CompactFeed title="Pipeline Feed" icon={Activity} items={pipelines.slice(0, 4).map((pipeline) => ({ id: pipeline.id, title: pipeline.project_path, detail: pipeline.likely_cause, badge: pipeline.status, tone: pipeline.status === "failed" ? "critical" as Tone : "neutral" as Tone }))} />
        <CompactFeed title="MR Coordination" icon={GitPullRequest} items={mergeRequests.slice(0, 4).map((mr) => ({ id: mr.id, title: `!${mr.merge_request_iid} ${mr.title}`, detail: mr.summary, badge: mr.bottleneck_level, tone: mr.bottleneck_level === "blocked" ? "critical" as Tone : "neutral" as Tone }))} />
        <CompactFeed title="Incidents" icon={AlertTriangle} items={incidents.slice(0, 4).map((incident) => ({ id: incident.id, title: incident.title, detail: incident.probable_root_cause, badge: incident.severity, tone: severityTone(incident.severity) }))} />
      </div>
    </>
  );
}

function RiskPanel({ risks, expandedRiskId, setExpandedRiskId, pulse }: { risks: Risk[]; expandedRiskId: number | null; setExpandedRiskId: (id: number | null) => void; pulse: (message: string) => void }) {
  return (
    <Panel title="Deployment Risk Center" icon={ShieldAlert} count={risks.length}>
      {risks.length ? (
        <div className="space-y-3">
          {risks.map((risk) => {
            const expanded = expandedRiskId === risk.id;
            return (
              <article key={risk.id} className="border border-slate-200 bg-white transition duration-150 hover:border-red-300 hover:shadow-sm">
                <button
                  type="button"
                  onClick={() => {
                    setExpandedRiskId(expanded ? null : risk.id);
                    pulse(expanded ? "Risk collapsed" : "Risk expanded");
                  }}
                  className="flex w-full items-start justify-between gap-3 p-4 text-left focus:outline-none focus:ring-2 focus:ring-teal-500 focus:ring-offset-2"
                >
                  <div>
                    <div className="flex flex-wrap gap-2">
                      <Badge label={`${risk.score}/100`} tone="critical" />
                      <Badge label={risk.level} tone="critical" />
                      {risk.merge_request_iid ? <Badge label={`MR !${risk.merge_request_iid}`} /> : null}
                    </div>
                    <h3 className="mt-3 font-semibold text-slate-950">{risk.project_path}</h3>
                    <p className="mt-1 text-sm leading-6 text-slate-600">{risk.summary}</p>
                  </div>
                  <ChevronDown size={18} className={`mt-1 text-slate-400 transition ${expanded ? "rotate-180" : ""}`} aria-hidden="true" />
                </button>
                {expanded ? (
                  <div className="border-t border-slate-200 px-4 pb-4 pt-3">
                    <DetailList title="Evidence" items={risk.reasons} />
                    <DetailList title="Next actions" items={risk.recommendations} />
                  </div>
                ) : null}
              </article>
            );
          })}
        </div>
      ) : (
        <EmptyState label="No deployment risks match the current search." />
      )}
    </Panel>
  );
}

function PipelinePanel({ pipelines }: { pipelines: PipelineInsight[] }) {
  return (
    <Panel title="Pipeline Intelligence Feed" icon={Activity} count={pipelines.length}>
      {pipelines.length ? (
        <div className="space-y-3">
          {pipelines.map((pipeline) => (
            <article key={pipeline.id} className="border border-slate-200 bg-white p-4 transition duration-150 hover:-translate-y-0.5 hover:border-amber-300 hover:shadow-sm">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div className="font-semibold text-slate-950">{pipeline.project_path}</div>
                <Badge label={pipeline.status} tone={pipeline.status === "failed" ? "critical" : "good"} />
              </div>
              <p className="mt-2 text-sm leading-6 text-slate-600">{pipeline.likely_cause}</p>
              <div className="mt-3 grid gap-3 md:grid-cols-2">
                <DetailList title="Evidence" items={pipeline.evidence} />
                <DetailList title="Recommendations" items={pipeline.recommendations} />
              </div>
            </article>
          ))}
        </div>
      ) : (
        <EmptyState label="No pipeline records match the current search." />
      )}
    </Panel>
  );
}

function ActionsPanel({ recommendations, selectedActionId, onSelect }: { recommendations: Recommendation[]; selectedActionId: number; onSelect: (id: number) => void }) {
  return (
    <Panel title="Action Queue" icon={Send} count={recommendations.length}>
      {recommendations.length ? (
        <div className="grid gap-3 lg:grid-cols-2">
          {recommendations.map((item) => {
            const selected = item.id === selectedActionId;
            return (
              <button
                type="button"
                key={item.id}
                onClick={() => onSelect(item.id)}
                aria-pressed={selected}
                className={`group border bg-white p-4 text-left transition duration-150 focus:outline-none focus:ring-2 focus:ring-teal-500 focus:ring-offset-2 active:scale-[0.99] ${
                  selected ? "border-teal-600 ring-1 ring-teal-600" : "border-slate-200 hover:-translate-y-0.5 hover:border-teal-500 hover:shadow-sm"
                }`}
              >
                <div className="flex flex-wrap items-center gap-2">
                  <Badge label={item.severity} tone={severityTone(item.severity)} />
                  <Badge label={item.status} tone={statusTone(item.status)} />
                  <Badge label={`${Math.round(item.confidence * 100)}%`} />
                </div>
                <h3 className="mt-3 font-semibold text-slate-950">{item.title || "Operational recommendation"}</h3>
                <p className="mt-2 line-clamp-3 text-sm leading-6 text-slate-600">{item.summary || item.message}</p>
                <div className="mt-3 flex items-center justify-between text-xs font-semibold uppercase text-slate-500">
                  <span>{item.action_type}</span>
                  <span className="text-teal-700 transition group-hover:translate-x-1">Inspect</span>
                </div>
              </button>
            );
          })}
        </div>
      ) : (
        <EmptyState label="No actions match the current search." />
      )}
    </Panel>
  );
}

function IncidentPanel({ incidents, memory }: { incidents: Incident[]; memory: MemoryRecord[] }) {
  return (
    <Panel title="Incident Explorer" icon={AlertTriangle} count={incidents.length}>
      {incidents.length ? (
        <div className="space-y-3">
          {incidents.map((incident) => (
            <article key={incident.id} className="border border-slate-200 bg-white p-4 transition duration-150 hover:-translate-y-0.5 hover:border-red-300 hover:shadow-sm">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <h3 className="font-semibold text-slate-950">{incident.title}</h3>
                <Badge label={incident.severity} tone={severityTone(incident.severity)} />
              </div>
              <p className="mt-2 text-sm leading-6 text-slate-600">{incident.probable_root_cause}</p>
              <DetailList title="Recommendations" items={incident.recommendations} />
            </article>
          ))}
        </div>
      ) : (
        <EmptyState label="No incidents match the current search." />
      )}
      {memory.length ? (
        <div className="mt-4 border-t border-slate-200 pt-4">
          <div className="mb-2 flex items-center gap-2 text-sm font-semibold text-slate-950">
            <History size={16} aria-hidden="true" />
            Recent operational memory
          </div>
          <div className="grid gap-2 md:grid-cols-2">
            {memory.slice(0, 4).map((record) => (
              <div key={record.id} className="border border-slate-200 bg-slate-50 p-3">
                <Badge label={record.memory_type} />
                <div className="mt-2 text-sm font-semibold text-slate-950">{record.project_path}</div>
                <p className="mt-1 line-clamp-2 text-sm text-slate-600">{record.summary}</p>
              </div>
            ))}
          </div>
        </div>
      ) : null}
    </Panel>
  );
}

function SelectedActionCard({ action }: { action?: Recommendation }) {
  if (!action) {
    return (
      <section className="border border-dashed border-slate-300 bg-white p-4">
        <div className="font-semibold text-slate-950">No action selected</div>
        <p className="mt-2 text-sm leading-6 text-slate-600">Select an action from the queue to inspect its evidence and next steps.</p>
      </section>
    );
  }

  return (
    <section className="border border-slate-200 bg-white p-4">
      <div className="flex items-center justify-between gap-3">
        <div className="flex items-center gap-2 font-semibold text-slate-950">
          <Send size={17} className="text-teal-700" aria-hidden="true" />
          Pinned Action
        </div>
        <Badge label={action.status} tone={statusTone(action.status)} />
      </div>
      <h3 className="mt-3 text-lg font-semibold text-slate-950">{action.title || "Operational recommendation"}</h3>
      <p className="mt-2 text-sm leading-6 text-slate-600">{action.summary || action.message}</p>

      <div className="mt-4 grid grid-cols-2 gap-2 text-sm">
        <Fact label="Severity" value={action.severity} tone={severityTone(action.severity)} />
        <Fact label="Confidence" value={`${Math.round(action.confidence * 100)}%`} />
        <Fact label="Channel" value={action.channel} />
        <Fact label="Approval" value={action.approval_state} />
      </div>

      {action.gemini_analysis ? (
        <div className="mt-4 border-l-2 border-teal-600 pl-3">
          <div className="text-xs font-semibold uppercase text-teal-700">Vertex Gemini Analysis</div>
          <p className="mt-1 whitespace-pre-line text-sm leading-6 text-slate-700">{action.gemini_analysis}</p>
        </div>
      ) : null}

      <div className="mt-4 space-y-3">
        <DetailList title="Evidence" items={action.evidence ?? []} />
        <DetailList title="Next actions" items={action.next_actions ?? []} />
      </div>

      <Link
        href="/actions"
        className="mt-4 inline-flex items-center gap-2 border border-teal-700 bg-teal-700 px-3 py-2 text-sm font-semibold text-white transition hover:-translate-y-0.5 hover:bg-teal-800 focus:outline-none focus:ring-2 focus:ring-teal-500 focus:ring-offset-2 active:translate-y-0"
      >
        Review approval
        <ArrowRight size={15} aria-hidden="true" />
      </Link>
    </section>
  );
}

function IntegrationPanel({ slackStatus }: { slackStatus: DashboardSummary["slack_status"] }) {
  const items = [
    { label: "Slack OAuth", ok: Boolean(slackStatus.oauth_connected), value: slackStatus.oauth_connected ? slackStatus.oauth_account_label || "Connected" : slackStatus.oauth_configured ? "Ready" : "Missing" },
    { label: "Webhook", ok: slackStatus.webhook_configured, value: slackStatus.webhook_configured ? "Configured" : "Missing" },
    { label: "Slack app", ok: slackStatus.signing_secret_configured, value: slackStatus.signing_secret_configured ? "Verified" : "Missing secret" },
    { label: "Bot token", ok: slackStatus.bot_token_configured, value: slackStatus.bot_token_configured ? "Configured" : "Missing" },
    { label: "Action mode", ok: slackStatus.mode !== "dry_run", value: slackStatus.mode }
  ];
  return (
    <section className="border border-slate-200 bg-white p-4">
      <div className="mb-3 flex items-center gap-2 font-semibold text-slate-950">
        <CheckCircle2 size={17} className="text-teal-700" aria-hidden="true" />
        Integration Status
      </div>
      <div className="space-y-2">
        {items.map((item) => (
          <div key={item.label} className="flex items-center justify-between gap-3 border-b border-slate-100 pb-2 last:border-b-0 last:pb-0">
            <span className="text-sm text-slate-600">{item.label}</span>
            <Badge label={item.value} tone={item.ok ? "good" : item.label === "Action mode" ? "warn" : "critical"} />
          </div>
        ))}
      </div>
      <a
        href={`${API_BASE}/api/integrations/slack/connect`}
        className="mt-4 inline-flex items-center gap-2 border border-teal-700 bg-teal-700 px-3 py-2 text-sm font-semibold text-white transition hover:-translate-y-0.5 hover:bg-teal-800 focus:outline-none focus:ring-2 focus:ring-teal-500 focus:ring-offset-2 active:translate-y-0"
      >
        Connect Slack
        <Send size={15} aria-hidden="true" />
      </a>
      {slackStatus.last_error ? <p className="mt-3 text-sm leading-6 text-red-700">{slackStatus.last_error}</p> : null}
    </section>
  );
}

function MemoryPanel({ memory }: { memory: MemoryRecord[] }) {
  return (
    <section className="border border-slate-200 bg-white p-4">
      <div className="mb-3 flex items-center gap-2 font-semibold text-slate-950">
        <History size={17} className="text-slate-700" aria-hidden="true" />
        Memory
      </div>
      {memory.length ? (
        <div className="space-y-3">
          {memory.slice(0, 3).map((record) => (
            <div key={record.id} className="border-l-2 border-slate-300 pl-3">
              <div className="text-sm font-semibold text-slate-950">{record.project_path}</div>
              <p className="mt-1 line-clamp-2 text-sm leading-6 text-slate-600">{record.summary}</p>
            </div>
          ))}
        </div>
      ) : (
        <p className="text-sm leading-6 text-slate-600">No operational memory recorded yet.</p>
      )}
    </section>
  );
}

function CompactFeed({ title, icon: Icon, items }: { title: string; icon: typeof Activity; items: Array<{ id: number; title: string; detail: string; badge: string; tone: Tone }> }) {
  return (
    <Panel title={title} icon={Icon} count={items.length}>
      {items.length ? (
        <div className="space-y-2">
          {items.map((item) => (
            <article key={item.id} className="border border-slate-200 bg-white p-3 transition duration-150 hover:-translate-y-0.5 hover:border-teal-400 hover:shadow-sm">
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0 font-semibold text-slate-950">{item.title}</div>
                <Badge label={item.badge} tone={item.tone} />
              </div>
              <p className="mt-1 line-clamp-2 text-sm leading-6 text-slate-600">{item.detail || "No detail recorded."}</p>
            </article>
          ))}
        </div>
      ) : (
        <EmptyState label={`No ${title.toLowerCase()} records match.`} />
      )}
    </Panel>
  );
}

function Panel({ title, icon: Icon, count, children }: { title: string; icon: typeof LayoutDashboard; count?: number; children: React.ReactNode }) {
  return (
    <section className="border border-slate-200 bg-white p-4">
      <div className="mb-4 flex items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <Icon size={18} className="text-teal-700" aria-hidden="true" />
          <h2 className="text-lg font-semibold text-slate-950">{title}</h2>
        </div>
        {typeof count === "number" ? <Badge label={`${count}`} /> : null}
      </div>
      {children}
    </section>
  );
}

function MetricCard({ icon: Icon, label, value, tone, hint }: { icon: typeof Activity; label: string; value: number; tone: Tone; hint: string }) {
  return (
    <article className="group border border-slate-200 bg-white p-4 transition duration-150 hover:-translate-y-0.5 hover:border-teal-400 hover:shadow-sm">
      <div className="flex items-start justify-between gap-3">
        <div>
          <div className="text-xs font-medium uppercase text-slate-500">{label}</div>
          <div className={`mt-2 text-3xl font-semibold ${toneColor(tone)}`}>{value}</div>
        </div>
        <Icon size={20} className={`transition group-hover:scale-110 ${toneColor(tone)}`} aria-hidden="true" />
      </div>
      <p className="mt-3 text-sm leading-6 text-slate-600">{hint}</p>
      <div className="mt-3 h-1.5 bg-slate-100">
        <div className={`h-full transition-all ${toneBar(tone)}`} style={{ width: `${Math.min(100, value * 18)}%` }} />
      </div>
    </article>
  );
}

function MiniMetric({ label, value, tone }: { label: string; value: number; tone: Tone }) {
  return (
    <div className="border border-slate-200 bg-white p-3">
      <div className="text-xs font-semibold uppercase text-slate-500">{label}</div>
      <div className={`mt-1 text-2xl font-semibold ${toneColor(tone)}`}>{value}</div>
    </div>
  );
}

function Fact({ label, value, tone = "neutral" }: { label: string; value: string; tone?: Tone }) {
  return (
    <div className="border border-slate-200 bg-slate-50 p-2">
      <div className="text-xs font-semibold uppercase text-slate-500">{label}</div>
      <div className={`mt-1 break-words text-sm ${toneColor(tone)}`}>{value || "unknown"}</div>
    </div>
  );
}

function PrimaryLink({ href, icon: Icon, label }: { href: string; icon: typeof Activity; label: string }) {
  return (
    <Link
      href={href}
      className="inline-flex items-center gap-2 border border-teal-700 bg-teal-700 px-3 py-2 text-sm font-semibold text-white transition duration-150 hover:-translate-y-0.5 hover:bg-teal-800 focus:outline-none focus:ring-2 focus:ring-teal-500 focus:ring-offset-2 active:translate-y-0"
    >
      <Icon size={16} aria-hidden="true" />
      {label}
    </Link>
  );
}

function SecondaryLink({ href, icon: Icon, label }: { href: string; icon: typeof Activity; label: string }) {
  return (
    <Link
      href={href}
      className="inline-flex items-center gap-2 border border-slate-300 bg-white px-3 py-2 text-sm font-semibold text-slate-700 transition duration-150 hover:-translate-y-0.5 hover:border-teal-500 hover:text-teal-700 focus:outline-none focus:ring-2 focus:ring-teal-500 focus:ring-offset-2 active:translate-y-0"
    >
      <Icon size={16} aria-hidden="true" />
      {label}
    </Link>
  );
}

function Badge({ label, tone = "neutral" }: { label: string; tone?: Tone }) {
  const styles = {
    neutral: "border-slate-200 bg-slate-50 text-slate-600",
    good: "border-emerald-200 bg-emerald-50 text-emerald-700",
    warn: "border-amber-200 bg-amber-50 text-amber-700",
    critical: "border-red-200 bg-red-50 text-red-700"
  };
  return <span className={`inline-flex items-center border px-2 py-1 text-xs font-semibold uppercase ${styles[tone]}`}>{label || "unknown"}</span>;
}

function DetailList({ title, items }: { title: string; items: string[] }) {
  return (
    <div>
      <div className="mt-3 text-xs font-semibold uppercase text-slate-500">{title}</div>
      {items.length ? (
        <ul className="mt-2 space-y-1 text-sm leading-6 text-slate-700">
          {items.slice(0, 4).map((item) => (
            <li key={item} className="flex gap-2">
              <CircleDot size={12} className="mt-1.5 shrink-0 text-teal-700" aria-hidden="true" />
              <span>{item}</span>
            </li>
          ))}
        </ul>
      ) : (
        <p className="mt-2 text-sm text-slate-500">None recorded.</p>
      )}
    </div>
  );
}

function EmptyState({ label }: { label: string }) {
  return (
    <div className="border border-dashed border-slate-300 bg-white p-5">
      <div className="flex items-center gap-2 font-semibold text-slate-950">
        <CheckCircle2 size={17} className="text-teal-700" aria-hidden="true" />
        Nothing to show
      </div>
      <p className="mt-2 text-sm leading-6 text-slate-600">{label}</p>
    </div>
  );
}

function filterDashboard({
  query,
  risks,
  pipelines,
  mergeRequests,
  incidents,
  recommendations
}: {
  query: string;
  risks: Risk[];
  pipelines: PipelineInsight[];
  mergeRequests: MergeRequestSignal[];
  incidents: Incident[];
  recommendations: Recommendation[];
}) {
  const q = query.trim().toLowerCase();
  if (!q) return { risks, pipelines, mergeRequests, incidents, recommendations };
  return {
    risks: risks.filter((item) => includes(item.project_path, item.summary, item.level, q)),
    pipelines: pipelines.filter((item) => includes(item.project_path, item.status, item.likely_cause, q)),
    mergeRequests: mergeRequests.filter((item) => includes(item.project_path, item.title, item.summary, item.bottleneck_level, q)),
    incidents: incidents.filter((item) => includes(item.project_path, item.title, item.probable_root_cause, item.severity, q)),
    recommendations: recommendations.filter((item) => includes(item.project_path, item.title, item.summary, item.message, item.channel, item.severity, q))
  };
}

function includes(...values: Array<string | undefined>) {
  const q = values[values.length - 1] ?? "";
  return values.slice(0, -1).some((value) => String(value ?? "").toLowerCase().includes(q));
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

function firstNextStep(recommendations: Recommendation[], risks: Risk[], pipelines: PipelineInsight[]) {
  const action = recommendations.find((item) => item.requires_approval) ?? recommendations[0];
  if (action) return `Start with ${action.title || action.action_type} for ${action.project_path}. It is ranked ${Math.round(action.rank_score)} with ${Math.round(action.confidence * 100)}% confidence.`;
  const risk = risks[0];
  if (risk) return `Start with ${risk.project_path}. It has ${risk.level} delivery risk at ${risk.score}/100.`;
  const pipeline = pipelines[0];
  if (pipeline) return `Start with the ${pipeline.project_path} pipeline because it is ${pipeline.status}.`;
  return "No urgent records are active. Sync GitLab projects or inspect metrics to continue.";
}

function severityTone(severity: string): Tone {
  if (severity === "critical" || severity === "high") return "critical";
  if (severity === "medium" || severity === "warning") return "warn";
  if (severity === "low") return "good";
  return "neutral";
}

function statusTone(status: string): Tone {
  if (["sent", "approved", "dry_run_mr_ready", "mr_opened"].includes(status)) return "good";
  if (["dry_run", "queued", "pending", "pending_approval", "draft"].includes(status)) return "warn";
  if (["failed", "rejected"].includes(status)) return "critical";
  return "neutral";
}

function toneColor(tone: Tone) {
  if (tone === "critical") return "text-red-700";
  if (tone === "warn") return "text-amber-700";
  if (tone === "good") return "text-emerald-700";
  return "text-slate-950";
}

function toneBar(tone: Tone) {
  if (tone === "critical") return "bg-red-600";
  if (tone === "warn") return "bg-amber-500";
  if (tone === "good") return "bg-emerald-600";
  return "bg-slate-500";
}
