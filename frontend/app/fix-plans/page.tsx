import Link from "next/link";
import { ArrowLeft, Bot, FileCode2, GitBranch, ShieldCheck } from "lucide-react";
import { FixPlan, getFixPlans, getProjectsData } from "@/lib/api";
import { FixPlanControls, NewFixPlanForm } from "./FixPlanControls";

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
  if (["approved", "branch_created", "dry_run_branch_ready", "mr_opened", "dry_run_mr_ready"].includes(status)) return "good";
  if (status === "draft") return "warn";
  if (["rejected", "failed"].includes(status)) return "critical";
  return "neutral";
}

function PlanCard({ plan }: { plan: FixPlan }) {
  const files = plan.plan_payload.files ?? [];
  const suggestions = plan.plan_payload.manual_patch_suggestions ?? [];
  const checklist = plan.plan_payload.review_checklist ?? [];

  return (
    <article className="border border-slate-200 bg-white p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="flex flex-wrap gap-2">
            <Badge label={plan.status} tone={statusTone(plan.status)} />
            <Badge label={plan.fix_type} />
            <Badge label={plan.requires_approval ? "approval required" : "no approval"} tone={plan.requires_approval ? "warn" : "good"} />
          </div>
          <h2 className="mt-3 text-lg font-semibold text-slate-950">{plan.title}</h2>
          <p className="mt-1 text-sm text-slate-600">{plan.project_path}</p>
        </div>
        <div className="text-right text-xs text-slate-500">
          <div>Base: {plan.base_branch}</div>
          <div className="mt-1 max-w-md truncate">Branch: {plan.branch_name}</div>
        </div>
      </div>

      <p className="mt-3 text-sm leading-6 text-slate-700">{plan.summary}</p>

      <div className="mt-4 grid gap-3 xl:grid-cols-2">
        <div className="border border-slate-200 bg-slate-50 p-3">
          <div className="mb-2 flex items-center gap-2 text-xs font-semibold uppercase text-slate-500">
            <FileCode2 size={14} />
            Planned Files
          </div>
          <div className="space-y-3">
            {files.map((file) => (
              <div key={file.path} className="border border-slate-200 bg-white p-3">
                <div className="flex flex-wrap items-center gap-2">
                  <Badge label={file.commit_action} />
                  <span className="text-sm font-semibold text-slate-950">{file.path}</span>
                </div>
                <p className="mt-2 text-sm leading-6 text-slate-600">{file.purpose}</p>
                <pre className="mt-2 max-h-44 overflow-auto whitespace-pre-wrap border border-slate-200 bg-slate-50 p-2 text-xs leading-5 text-slate-700">
                  {file.content}
                </pre>
              </div>
            ))}
          </div>
        </div>

        <div className="space-y-3">
          <div className="border border-slate-200 bg-slate-50 p-3">
            <div className="mb-2 flex items-center gap-2 text-xs font-semibold uppercase text-slate-500">
              <ShieldCheck size={14} />
              Safety Checklist
            </div>
            <ul className="space-y-2 text-sm text-slate-700">
              {checklist.map((item) => (
                <li key={item}>- {item}</li>
              ))}
            </ul>
          </div>

          {suggestions.length ? (
            <div className="border border-slate-200 bg-slate-50 p-3">
              <div className="text-xs font-semibold uppercase text-slate-500">Manual Patch Suggestions</div>
              <div className="mt-2 space-y-2">
                {suggestions.map((item) => (
                  <div key={item.path} className="border border-slate-200 bg-white p-3 text-sm">
                    <div className="font-semibold text-slate-950">{item.path}</div>
                    <p className="mt-1 text-slate-600">{item.reason}</p>
                    <p className="mt-1 text-slate-700">{item.suggestion}</p>
                  </div>
                ))}
              </div>
            </div>
          ) : null}
        </div>
      </div>

      {plan.merge_request_url ? (
        <a href={plan.merge_request_url} target="_blank" rel="noreferrer" className="mt-4 inline-flex items-center gap-2 text-sm font-semibold text-teal-700">
          <GitBranch size={15} />
          Open merge request
        </a>
      ) : null}

      <FixPlanControls planId={plan.id} status={plan.status} />
    </article>
  );
}

export default async function FixPlansPage() {
  const [{ projects }, plans] = await Promise.all([getProjectsData(), getFixPlans()]);

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
              <Bot className="text-teal-700" size={24} />
              <h1 className="text-2xl font-semibold">Safe Fix Plans</h1>
            </div>
            <p className="mt-1 text-sm text-slate-600">Generate, approve, and dry-run GitLab branch/MR fixes before anything touches a repository.</p>
          </div>
          <div className="text-sm text-slate-600">{plans.length} plan{plans.length === 1 ? "" : "s"}</div>
        </div>
      </header>

      <div className="mx-auto max-w-7xl space-y-4 px-6 py-6">
        <NewFixPlanForm projects={projects} />

        {plans.length ? (
          <div className="space-y-3">
            {plans.map((plan) => (
              <PlanCard key={plan.id} plan={plan} />
            ))}
          </div>
        ) : (
          <div className="border border-dashed border-slate-300 bg-white p-6 text-sm text-slate-600">
            No fix plans yet. Create one from a synced project to review the planned files and approval flow.
          </div>
        )}
      </div>
    </main>
  );
}
