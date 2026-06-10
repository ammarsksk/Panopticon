import Link from "next/link";
import { ArrowLeft, Bot, CheckCircle2, FileCode2, GitBranch, GitCommitHorizontal, ShieldCheck } from "lucide-react";
import { FixPlan, getFixPlans, getProjectsData } from "@/lib/api";
import { redirectIfUnauthorized } from "../authRedirect";
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

type DiffRow = {
  key: string;
  type: "meta" | "hunk" | "add" | "delete" | "context";
  sign: string;
  text: string;
  oldLine: number | null;
  newLine: number | null;
};

function parseUnifiedDiff(diff: string): DiffRow[] {
  let oldLine = 0;
  let newLine = 0;
  return diff.split("\n").map((line, index) => {
    if (line.startsWith("@@")) {
      const match = line.match(/@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@/);
      oldLine = match ? Number(match[1]) : oldLine;
      newLine = match ? Number(match[2]) : newLine;
      return { key: `${index}-hunk`, type: "hunk", sign: "", text: line, oldLine: null, newLine: null };
    }
    if (line.startsWith("---") || line.startsWith("+++")) {
      return { key: `${index}-meta`, type: "meta", sign: "", text: line, oldLine: null, newLine: null };
    }
    if (line.startsWith("+")) {
      const row = { key: `${index}-add`, type: "add" as const, sign: "+", text: line.slice(1), oldLine: null, newLine };
      newLine += 1;
      return row;
    }
    if (line.startsWith("-")) {
      const row = { key: `${index}-delete`, type: "delete" as const, sign: "-", text: line.slice(1), oldLine, newLine: null };
      oldLine += 1;
      return row;
    }
    const row = {
      key: `${index}-context`,
      type: "context" as const,
      sign: line ? " " : "",
      text: line.startsWith(" ") ? line.slice(1) : line,
      oldLine,
      newLine
    };
    oldLine += 1;
    newLine += 1;
    return row;
  });
}

function diffStats(diff: string) {
  return diff.split("\n").reduce(
    (acc, line) => {
      if (line.startsWith("+") && !line.startsWith("+++")) acc.additions += 1;
      if (line.startsWith("-") && !line.startsWith("---")) acc.deletions += 1;
      return acc;
    },
    { additions: 0, deletions: 0 }
  );
}

function DiffPreview({ item }: { item: { path: string; commit_action: string; diff: string } }) {
  const rows = parseUnifiedDiff(item.diff || "");
  const stats = diffStats(item.diff || "");
  const isCreate = item.commit_action === "create";
  return (
    <section className="overflow-hidden border border-slate-200 bg-white">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-200 bg-slate-50 px-3 py-2">
        <div className="flex min-w-0 flex-wrap items-center gap-2">
          <Badge label={item.commit_action} tone={isCreate ? "good" : "neutral"} />
          <span className="truncate font-mono text-sm font-semibold text-slate-950">{item.path}</span>
        </div>
        <div className="flex items-center gap-2 text-xs font-semibold">
          <span className="text-emerald-700">+{stats.additions}</span>
          <span className="text-red-700">-{stats.deletions}</span>
        </div>
      </div>
      {rows.length ? (
        <div className="max-h-[460px] overflow-auto bg-white font-mono text-xs leading-5">
          <div className="min-w-max">
            {rows.map((row) => {
              const styles = {
                add: "border-l-2 border-emerald-500 bg-emerald-50 text-emerald-950",
                delete: "border-l-2 border-red-500 bg-red-50 text-red-950",
                hunk: "border-l-2 border-teal-500 bg-teal-50 text-teal-900",
                meta: "border-l-2 border-slate-300 bg-slate-100 text-slate-600",
                context: "border-l-2 border-transparent bg-white text-slate-700"
              }[row.type];
              return (
                <div key={row.key} className={`grid min-w-full grid-cols-[52px_52px_28px_minmax(84ch,1fr)] ${styles}`}>
                  <span className="select-none border-r border-slate-200 px-2 py-0.5 text-right text-slate-500">{row.oldLine ?? ""}</span>
                  <span className="select-none border-r border-slate-200 px-2 py-0.5 text-right text-slate-500">{row.newLine ?? ""}</span>
                  <span className="select-none px-2 py-0.5 font-bold">{row.sign}</span>
                  <span className="whitespace-pre px-1 py-0.5">{row.text || " "}</span>
                </div>
              );
            })}
          </div>
        </div>
      ) : (
        <div className="p-3 text-sm text-slate-600">No textual diff available for this file.</div>
      )}
    </section>
  );
}

function PlanExecutionSummary({ plan }: { plan: FixPlan }) {
  const files = plan.plan_payload.files ?? [];
  const updateCount = files.filter((file) => file.commit_action === "update").length;
  const createCount = files.filter((file) => file.commit_action === "create").length;
  const writesPrepared = ["branch_created", "dry_run_branch_ready", "mr_opened", "dry_run_mr_ready"].includes(plan.status);
  return (
    <div className="mt-4 grid gap-3 lg:grid-cols-3">
      <div className="border border-slate-200 bg-slate-50 p-3">
        <div className="flex items-center gap-2 text-xs font-semibold uppercase text-slate-500">
          <GitCommitHorizontal size={14} />
          Code impact
        </div>
        <p className="mt-2 text-sm text-slate-700">
          {updateCount} update{updateCount === 1 ? "" : "s"} and {createCount} new file{createCount === 1 ? "" : "s"} prepared.
        </p>
      </div>
      <div className="border border-slate-200 bg-slate-50 p-3">
        <div className="flex items-center gap-2 text-xs font-semibold uppercase text-slate-500">
          <ShieldCheck size={14} />
          Write behavior
        </div>
        <p className="mt-2 text-sm text-slate-700">
          {writesPrepared ? "Branch/MR step has been requested." : "Draft only. No repository write happens until approval and branch creation."}
        </p>
      </div>
      <div className="border border-slate-200 bg-slate-50 p-3">
        <div className="flex items-center gap-2 text-xs font-semibold uppercase text-slate-500">
          <CheckCircle2 size={14} />
          Review rule
        </div>
        <p className="mt-2 text-sm text-slate-700">Review the colored diff and validation commands before creating a branch.</p>
      </div>
    </div>
  );
}

function PlanCard({ plan }: { plan: FixPlan }) {
  const files = plan.plan_payload.files ?? [];
  const suggestions = plan.plan_payload.manual_patch_suggestions ?? [];
  const checklist = plan.plan_payload.review_checklist ?? [];
  const diffs = plan.plan_payload.diff_preview ?? [];
  const evidence = plan.plan_payload.evidence_bundle ?? [];
  const validation = plan.plan_payload.validation ?? {};
  const testCommands = plan.plan_payload.test_plan?.commands ?? [];
  const rollback = plan.plan_payload.rollback ?? [];

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
      <PlanExecutionSummary plan={plan} />

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
                <details className="mt-2 border border-slate-200 bg-slate-50">
                  <summary className="cursor-pointer px-3 py-2 text-xs font-semibold uppercase text-slate-500">View proposed file content</summary>
                  <pre className="max-h-56 overflow-auto whitespace-pre-wrap border-t border-slate-200 p-3 text-xs leading-5 text-slate-700">
                    {file.content}
                  </pre>
                </details>
              </div>
            ))}
          </div>
        </div>

        <div className="space-y-3">
          <div className="border border-slate-200 bg-slate-50 p-3">
            <div className="mb-2 flex items-center gap-2 text-xs font-semibold uppercase text-slate-500">
              <ShieldCheck size={14} />
              Safety Validation
            </div>
            <div className="grid gap-2 text-sm text-slate-700 sm:grid-cols-2">
              <div>Branch safe: {validation.branch_safe ? "yes" : "check"}</div>
              <div>MR required: {validation.merge_request_required ? "yes" : "check"}</div>
              <div>Evidence: {validation.evidence_count ?? 0} item(s)</div>
              <div>Diffs: {validation.diff_preview_available ? "available" : "missing"}</div>
            </div>
            {validation.unsafe_paths?.length ? <p className="mt-2 text-sm text-red-700">Unsafe paths: {validation.unsafe_paths.join(", ")}</p> : null}
          </div>

          {diffs.length ? (
            <div className="border border-slate-200 bg-slate-50 p-3">
              <div className="flex items-center justify-between gap-3">
                <div className="text-xs font-semibold uppercase text-slate-500">GitHub-style Diff Preview</div>
                <div className="text-xs text-slate-500">{diffs.length} file{diffs.length === 1 ? "" : "s"}</div>
              </div>
              <div className="mt-2 space-y-2">
                {diffs.map((item) => (
                  <DiffPreview key={item.path} item={item} />
                ))}
              </div>
            </div>
          ) : null}

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

          {testCommands.length ? (
            <div className="border border-slate-200 bg-slate-50 p-3">
              <div className="text-xs font-semibold uppercase text-slate-500">Validation Commands</div>
              <ul className="mt-2 space-y-1 text-sm text-slate-700">
                {testCommands.map((command) => (
                  <li key={command}>- {command}</li>
                ))}
              </ul>
              <p className="mt-2 text-xs text-slate-500">{plan.plan_payload.test_plan?.execution_note}</p>
            </div>
          ) : null}

          {evidence.length ? (
            <div className="border border-slate-200 bg-slate-50 p-3">
              <div className="text-xs font-semibold uppercase text-slate-500">Evidence Bundle</div>
              <div className="mt-2 space-y-2">
                {evidence.slice(0, 6).map((item, index) => (
                  <div key={`${item.type}-${item.id ?? item.file_path ?? index}`} className="border border-slate-200 bg-white p-3 text-sm">
                    <div className="font-semibold text-slate-950">{item.label}</div>
                    <p className="mt-1 text-slate-600">{item.summary}</p>
                  </div>
                ))}
              </div>
            </div>
          ) : null}

          {rollback.length ? (
            <div className="border border-slate-200 bg-slate-50 p-3">
              <div className="text-xs font-semibold uppercase text-slate-500">Rollback</div>
              <ul className="mt-2 space-y-1 text-sm text-slate-700">
                {rollback.map((item) => (
                  <li key={item}>- {item}</li>
                ))}
              </ul>
            </div>
          ) : null}

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
  let data;
  try {
    data = await Promise.all([getProjectsData(), getFixPlans()]);
  } catch (error) {
    redirectIfUnauthorized(error);
  }
  const [{ projects }, plans] = data;

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
