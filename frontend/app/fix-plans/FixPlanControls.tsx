"use client";

import { useState } from "react";
import { Check, GitBranch, GitPullRequest, Plus, X } from "lucide-react";
import {
  approveFixPlan,
  createFixPlan,
  createFixPlanBranch,
  GitLabProject,
  openFixPlanMergeRequest,
  rejectFixPlan
} from "@/lib/api";

const FIX_TYPES = [
  { value: "pipeline_timeout", label: "Pipeline timeout" },
  { value: "test_scaffold", label: "Test scaffold" },
  { value: "deployment_healthcheck", label: "Deployment healthcheck" },
  { value: "rollback_runbook", label: "Rollback runbook" },
  { value: "ci_retry_guidance", label: "CI retry guidance" },
  { value: "source_validation", label: "Source validation" },
  { value: "source_logging", label: "Source logging" },
  { value: "source_bug_fix", label: "Source bug fix" },
  { value: "documentation_update", label: "Documentation update" },
  { value: "config_validation", label: "Config validation" },
  { value: "generic_code_change", label: "Generic code change" }
];

export function NewFixPlanForm({ projects }: { projects: GitLabProject[] }) {
  const [projectId, setProjectId] = useState(projects[0]?.id ?? 0);
  const [fixType, setFixType] = useState(FIX_TYPES[0].value);
  const [problem, setProblem] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");

  async function submit() {
    if (!projectId) return;
    setBusy(true);
    setMessage("");
    try {
      await createFixPlan({
        project_id: projectId,
        fix_type: fixType,
        problem_statement: problem || "Prepare a safe remediation plan from current Panopticon context."
      });
      setMessage("Fix plan created. Refreshing...");
      window.setTimeout(() => window.location.reload(), 600);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Failed to create fix plan.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="border border-slate-200 bg-white p-4">
      <div className="mb-3 flex items-center gap-2 font-semibold text-slate-950">
        <Plus size={17} />
        New Fix Plan
      </div>
      <div className="grid gap-3 lg:grid-cols-[1fr_220px]">
        <select
          value={projectId}
          onChange={(event) => setProjectId(Number(event.target.value))}
          className="border border-slate-300 bg-white px-3 py-2 text-sm"
        >
          {projects.map((project) => (
            <option key={project.id} value={project.id}>
              {project.project_path}
            </option>
          ))}
        </select>
        <select value={fixType} onChange={(event) => setFixType(event.target.value)} className="border border-slate-300 bg-white px-3 py-2 text-sm">
          {FIX_TYPES.map((item) => (
            <option key={item.value} value={item.value}>
              {item.label}
            </option>
          ))}
        </select>
      </div>
      <textarea
        value={problem}
        onChange={(event) => setProblem(event.target.value)}
        rows={3}
        placeholder="Describe the failure or remediation goal."
        className="mt-3 w-full border border-slate-300 bg-white px-3 py-2 text-sm"
      />
      <button
        type="button"
        onClick={submit}
        disabled={busy || !projectId}
        className="mt-3 inline-flex items-center gap-2 border border-teal-700 bg-teal-700 px-3 py-2 text-sm font-semibold text-white disabled:cursor-not-allowed disabled:border-slate-300 disabled:bg-slate-300"
      >
        <Plus size={15} />
        {busy ? "Creating" : "Create Fix Plan"}
      </button>
      {message ? <p className="mt-2 text-sm text-slate-600">{message}</p> : null}
    </div>
  );
}

export function FixPlanControls({ planId, status }: { planId: number; status: string }) {
  const [busy, setBusy] = useState("");
  const terminal = ["rejected", "mr_opened", "dry_run_mr_ready"].includes(status);

  async function run(operation: "approve" | "reject" | "branch" | "mr") {
    setBusy(operation);
    try {
      if (operation === "approve") await approveFixPlan(planId);
      if (operation === "reject") await rejectFixPlan(planId);
      if (operation === "branch") await createFixPlanBranch(planId);
      if (operation === "mr") await openFixPlanMergeRequest(planId);
      window.location.reload();
    } finally {
      setBusy("");
    }
  }

  return (
    <div className="mt-4 flex flex-wrap gap-2">
      <button
        type="button"
        onClick={() => run("approve")}
        disabled={terminal || status === "approved" || busy !== ""}
        className="inline-flex items-center gap-2 border border-emerald-700 px-3 py-2 text-sm font-semibold text-emerald-700 disabled:cursor-not-allowed disabled:border-slate-300 disabled:text-slate-400"
      >
        <Check size={15} />
        {busy === "approve" ? "Approving" : "Approve"}
      </button>
      <button
        type="button"
        onClick={() => run("reject")}
        disabled={terminal || busy !== ""}
        className="inline-flex items-center gap-2 border border-red-700 px-3 py-2 text-sm font-semibold text-red-700 disabled:cursor-not-allowed disabled:border-slate-300 disabled:text-slate-400"
      >
        <X size={15} />
        {busy === "reject" ? "Rejecting" : "Reject"}
      </button>
      <button
        type="button"
        onClick={() => run("branch")}
        disabled={status !== "approved" || busy !== ""}
        className="inline-flex items-center gap-2 border border-teal-700 px-3 py-2 text-sm font-semibold text-teal-700 disabled:cursor-not-allowed disabled:border-slate-300 disabled:text-slate-400"
      >
        <GitBranch size={15} />
        {busy === "branch" ? "Preparing Branch" : "Create Branch"}
      </button>
      <button
        type="button"
        onClick={() => run("mr")}
        disabled={!["branch_created", "dry_run_branch_ready"].includes(status) || busy !== ""}
        className="inline-flex items-center gap-2 border border-teal-700 bg-teal-700 px-3 py-2 text-sm font-semibold text-white disabled:cursor-not-allowed disabled:border-slate-300 disabled:bg-slate-300"
      >
        <GitPullRequest size={15} />
        {busy === "mr" ? "Opening MR" : "Open MR"}
      </button>
    </div>
  );
}
