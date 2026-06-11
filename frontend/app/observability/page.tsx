"use client";

import Link from "next/link";
import { Activity, AlertTriangle, ArrowLeft, Gauge, RadioTower } from "lucide-react";
import { getObservabilityData, IncidentCorrelation, ObservabilityEvent } from "@/lib/api";
import { ProtectedClientPage } from "../ProtectedClientPage";

function Badge({ label, tone = "neutral" }: { label: string; tone?: "neutral" | "good" | "warn" | "critical" }) {
  const styles = {
    neutral: "border-slate-200 bg-slate-50 text-slate-600",
    good: "border-emerald-200 bg-emerald-50 text-emerald-700",
    warn: "border-amber-200 bg-amber-50 text-amber-700",
    critical: "border-red-200 bg-red-50 text-red-700"
  };
  return <span className={`border px-2 py-1 text-xs font-semibold uppercase ${styles[tone]}`}>{label || "unknown"}</span>;
}

function severityTone(severity: string): "neutral" | "good" | "warn" | "critical" {
  if (["critical", "high"].includes(severity)) return "critical";
  if (["medium", "warning"].includes(severity)) return "warn";
  if (["low"].includes(severity)) return "good";
  return "neutral";
}

function formatDate(value: string) {
  return value ? new Date(value).toLocaleString() : "unknown";
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

function CorrelationCard({ correlation }: { correlation: IncidentCorrelation }) {
  return (
    <article className="border border-slate-200 bg-white p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="flex flex-wrap gap-2">
            <Badge label={correlation.severity} tone={severityTone(correlation.severity)} />
            <Badge label={correlation.status} tone={correlation.status === "open" ? "warn" : "neutral"} />
            <Badge label={`${Math.round(correlation.confidence * 100)}% confidence`} />
          </div>
          <h2 className="mt-3 text-lg font-semibold text-slate-950">{correlation.title}</h2>
          <p className="mt-1 text-sm text-slate-600">{correlation.project_path || "unmapped project"}</p>
        </div>
        <div className="text-xs text-slate-500">{formatDate(correlation.updated_at)}</div>
      </div>

      <p className="mt-3 text-sm leading-6 text-slate-700">{correlation.summary}</p>
      <div className="mt-4 border-l-2 border-teal-600 pl-3">
        <div className="text-xs font-semibold uppercase text-teal-700">Suspected Cause</div>
        <p className="mt-1 text-sm leading-6 text-slate-700">{correlation.suspected_cause}</p>
      </div>

      <div className="mt-4 grid gap-3 lg:grid-cols-[1.3fr_1fr]">
        <div>
          <div className="mb-2 text-xs font-semibold uppercase text-slate-500">Timeline</div>
          <div className="space-y-2">
            {correlation.timeline.slice(0, 8).map((item, index) => (
              <div key={`${item.kind}-${item.id}-${index}`} className="border border-slate-200 bg-slate-50 p-3">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div className="flex flex-wrap items-center gap-2">
                    <Badge label={item.kind} />
                    <span className="text-sm font-semibold text-slate-950">{item.title}</span>
                  </div>
                  <span className="text-xs text-slate-500">{formatDate(item.time)}</span>
                </div>
                <p className="mt-2 text-sm leading-6 text-slate-600">{item.detail || "No detail recorded."}</p>
              </div>
            ))}
          </div>
        </div>

        <div>
          <div className="mb-2 text-xs font-semibold uppercase text-slate-500">Recommendations</div>
          <ul className="space-y-2 text-sm leading-6 text-slate-700">
            {correlation.recommendations.map((item) => (
              <li key={item}>- {item}</li>
            ))}
          </ul>
          <div className="mt-4 grid grid-cols-2 gap-2 text-xs text-slate-600">
            <div className="border border-slate-200 bg-slate-50 p-2">Events: {correlation.related_observability_event_ids.length}</div>
            <div className="border border-slate-200 bg-slate-50 p-2">Pipelines: {correlation.related_pipeline_ids.length}</div>
            <div className="border border-slate-200 bg-slate-50 p-2">Risks: {correlation.related_risk_ids.length}</div>
            <div className="border border-slate-200 bg-slate-50 p-2">Incidents: {correlation.related_incident_ids.length}</div>
          </div>
        </div>
      </div>
    </article>
  );
}

function EventCard({ event }: { event: ObservabilityEvent }) {
  return (
    <article className="border border-slate-200 bg-white p-4">
      <div className="flex flex-wrap items-center gap-2">
        <Badge label={event.severity} tone={severityTone(event.severity)} />
        <Badge label={event.provider} />
        <Badge label={event.signal_type} />
      </div>
      <h3 className="mt-3 font-semibold text-slate-950">{event.title}</h3>
      <p className="mt-1 text-sm text-slate-600">{event.project_path || event.service_name || "unmapped service"}</p>
      <p className="mt-3 text-sm leading-6 text-slate-700">{event.message}</p>
      <div className="mt-3 flex flex-wrap gap-3 text-xs text-slate-500">
        <span>{event.environment || "unknown env"}</span>
        <span>{event.metric_name || "no metric"}</span>
        <span>{formatDate(event.observed_at)}</span>
      </div>
      {event.alert_url ? (
        <a href={event.alert_url} target="_blank" rel="noreferrer" className="mt-3 inline-flex text-sm font-semibold text-teal-700">
          Open source alert
        </a>
      ) : null}
    </article>
  );
}

export default function ObservabilityPage() {
  return (
    <ProtectedClientPage load={getObservabilityData} title="Opening observability">
      {({ events, correlations, projects }) => {
        const critical = correlations.filter((item) => ["critical", "high"].includes(item.severity)).length;
        const unmapped = events.filter((item) => !item.project_path).length;
        return (
          <main className="min-h-screen bg-slate-50 text-slate-950">
            <header className="border-b border-slate-200 bg-white">
              <div className="mx-auto flex max-w-7xl items-center justify-between gap-4 px-6 py-5">
                <div>
                  <Link href="/dashboard" className="mb-3 inline-flex items-center gap-2 text-sm font-medium text-teal-700">
                    <ArrowLeft size={16} />
                    Dashboard
                  </Link>
                  <div className="flex items-center gap-2">
                    <RadioTower className="text-teal-700" size={24} />
                    <h1 className="text-2xl font-semibold">Observability Correlation</h1>
                  </div>
                  <p className="mt-1 text-sm text-slate-600">Production alerts correlated with GitLab pipelines, jobs, delivery risks, and incidents.</p>
                </div>
                <div className="text-sm text-slate-600">{projects.length} synced project{projects.length === 1 ? "" : "s"}</div>
              </div>
            </header>

            <div className="mx-auto max-w-7xl px-6 py-6">
              <div className="grid gap-3 md:grid-cols-4">
                <Metric label="Observability events" value={events.length} />
                <Metric label="Correlations" value={correlations.length} />
                <Metric label="Critical or high" value={critical} tone={critical ? "critical" : "neutral"} />
                <Metric label="Unmapped services" value={unmapped} tone={unmapped ? "warn" : "neutral"} />
              </div>

        <section className="border-t border-slate-200 py-6">
          <div className="mb-4 flex items-center gap-2">
            <AlertTriangle className="text-red-700" size={20} />
            <h2 className="text-lg font-semibold text-slate-950">Incident Correlations</h2>
          </div>
          {correlations.length ? (
            <div className="space-y-3">
              {correlations.map((correlation) => (
                <CorrelationCard key={correlation.id} correlation={correlation} />
              ))}
            </div>
          ) : (
            <div className="border border-dashed border-slate-300 bg-white p-6 text-sm text-slate-600">
              No observability correlations yet. Send a generic alert to `/webhooks/observability/grafana`, `/webhooks/observability/prometheus`, or `/api/observability/events`.
            </div>
          )}
        </section>

        <section className="border-t border-slate-200 py-6">
          <div className="mb-4 flex items-center gap-2">
            <Activity className="text-amber-700" size={20} />
            <h2 className="text-lg font-semibold text-slate-950">Recent Signals</h2>
          </div>
          {events.length ? (
            <div className="grid gap-3 lg:grid-cols-2">
              {events.map((event) => (
                <EventCard key={event.id} event={event} />
              ))}
            </div>
          ) : (
            <div className="border border-dashed border-slate-300 bg-white p-6 text-sm text-slate-600">No observability events ingested yet.</div>
          )}
        </section>

        <section className="border-t border-slate-200 py-6">
          <div className="mb-4 flex items-center gap-2">
            <Gauge className="text-teal-700" size={20} />
            <h2 className="text-lg font-semibold text-slate-950">Ingestion Contract</h2>
          </div>
          <pre className="overflow-auto border border-slate-200 bg-white p-4 text-xs leading-5 text-slate-700">
{`POST /webhooks/observability/grafana
{
  "service_name": "checkout-service",
  "project_path": "demo/checkout-service",
  "environment": "production",
  "severity": "critical",
  "signal_type": "metric_alert",
  "title": "checkout error rate spike",
  "message": "5xx rate exceeded threshold after deploy",
  "metric_name": "http_5xx_rate",
  "alert_url": "https://grafana.example/alert/123"
}`}
          </pre>
        </section>
            </div>
          </main>
        );
      }}
    </ProtectedClientPage>
  );
}
