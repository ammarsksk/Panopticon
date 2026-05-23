import Link from "next/link";
import { ArrowLeft, ClipboardCheck, FileText, History, ShieldCheck } from "lucide-react";
import { AgentAction, getAgentActions } from "@/lib/api";
import { redirectIfUnauthorized } from "../authRedirect";
import { ActionControls, PrepareActionsButton } from "./ActionControls";

function Badge({ label, tone = "neutral" }: { label: string; tone?: "neutral" | "good" | "warn" | "critical" }) {
  const styles = {
    neutral: "border-slate-200 bg-slate-50 text-slate-600",
    good: "border-emerald-200 bg-emerald-50 text-emerald-700",
    warn: "border-amber-200 bg-amber-50 text-amber-700",
    critical: "border-red-200 bg-red-50 text-red-700"
  };
  return <span className={`border px-2 py-1 text-xs font-semibold uppercase ${styles[tone]}`}>{label || "unknown"}</span>;
}

function statusTone(status: string): "neutral" | "good" | "warn" | "critical" {
  if (["approved", "sent", "dry_run"].includes(status)) return "good";
  if (["pending_approval", "executing"].includes(status)) return "warn";
  if (["rejected", "failed"].includes(status)) return "critical";
  return "neutral";
}

function ActionCard({ action }: { action: AgentAction }) {
  return (
    <article className="border border-slate-200 bg-white p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="flex flex-wrap gap-2">
            <Badge label={action.status} tone={statusTone(action.status)} />
            <Badge label={action.action_type} />
            <Badge label={action.requires_approval ? "approval required" : "no approval"} tone={action.requires_approval ? "warn" : "good"} />
          </div>
          <h2 className="mt-3 text-lg font-semibold text-slate-950">{action.title}</h2>
          <p className="mt-1 text-sm text-slate-600">{action.project_path}</p>
        </div>
        <div className="text-xs uppercase text-slate-500">{action.channel}</div>
      </div>

      <p className="mt-3 text-sm leading-6 text-slate-700">{action.summary || "No summary recorded."}</p>

      <div className="mt-4 grid gap-3 lg:grid-cols-2">
        <div className="border border-slate-200 bg-slate-50 p-3">
          <div className="mb-2 flex items-center gap-2 text-xs font-semibold uppercase text-slate-500">
            <FileText size={14} />
            Payload Preview
          </div>
          <pre className="max-h-56 overflow-auto whitespace-pre-wrap text-xs leading-5 text-slate-700">{JSON.stringify(action.payload_preview, null, 2)}</pre>
        </div>
        <div className="border border-slate-200 bg-slate-50 p-3">
          <div className="mb-2 flex items-center gap-2 text-xs font-semibold uppercase text-slate-500">
            <History size={14} />
            Last Result
          </div>
          <pre className="max-h-56 overflow-auto whitespace-pre-wrap text-xs leading-5 text-slate-700">{JSON.stringify(action.last_result, null, 2)}</pre>
          {action.error ? <p className="mt-2 text-sm text-red-700">{action.error}</p> : null}
        </div>
      </div>

      <ActionControls actionId={action.id} status={action.status} />
    </article>
  );
}

export default async function ActionsPage() {
  let actions;
  try {
    actions = await getAgentActions();
  } catch (error) {
    redirectIfUnauthorized(error);
  }

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
              <ShieldCheck className="text-teal-700" size={24} />
              <h1 className="text-2xl font-semibold">Action Approvals</h1>
            </div>
            <p className="mt-1 text-sm text-slate-600">Approve, reject, and execute Panopticon actions with payload previews.</p>
          </div>
          <PrepareActionsButton />
        </div>
      </header>

      <div className="mx-auto max-w-7xl px-6 py-6">
        <div className="mb-4 flex flex-wrap gap-2">
          <Badge label={`${actions.length} actions`} />
          <Badge label={`${actions.filter((item) => item.status === "pending_approval").length} pending approval`} tone="warn" />
          <Badge label={`${actions.filter((item) => item.status === "approved").length} approved`} tone="good" />
        </div>

        {actions.length ? (
          <div className="space-y-3">
            {actions.map((action) => (
              <ActionCard key={action.id} action={action} />
            ))}
          </div>
        ) : (
          <div className="border border-dashed border-slate-300 bg-white p-6">
            <div className="flex items-center gap-2 font-semibold text-slate-950">
              <ClipboardCheck size={18} />
              No proposed actions yet.
            </div>
            <p className="mt-2 text-sm leading-6 text-slate-600">
              Use Prepare Actions to convert executable recommendations into approval-gated actions.
            </p>
          </div>
        )}
      </div>
    </main>
  );
}
