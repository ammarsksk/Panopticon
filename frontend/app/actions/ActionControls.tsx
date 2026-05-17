"use client";

import { useState } from "react";
import { Check, Play, RefreshCw, X } from "lucide-react";
import { approveAgentAction, executeAgentAction, proposeAgentActions, rejectAgentAction } from "@/lib/api";

export function PrepareActionsButton() {
  const [state, setState] = useState<"idle" | "running" | "done" | "failed">("idle");
  const [message, setMessage] = useState("");

  async function prepare() {
    setState("running");
    setMessage("");
    try {
      const actions = await proposeAgentActions();
      setState("done");
      setMessage(`Prepared ${actions.length} action${actions.length === 1 ? "" : "s"}. Refreshing...`);
      window.setTimeout(() => window.location.reload(), 600);
    } catch (error) {
      setState("failed");
      setMessage(error instanceof Error ? error.message : "Failed to prepare actions.");
    }
  }

  return (
    <div className="flex flex-col items-start gap-2">
      <button
        type="button"
        onClick={prepare}
        disabled={state === "running"}
        className="inline-flex items-center gap-2 border border-teal-700 bg-teal-700 px-3 py-2 text-sm font-semibold text-white disabled:cursor-not-allowed disabled:border-slate-300 disabled:bg-slate-300"
      >
        <RefreshCw size={16} className={state === "running" ? "animate-spin" : ""} />
        {state === "running" ? "Preparing Actions" : "Prepare Actions"}
      </button>
      {message ? <p className={`text-sm ${state === "failed" ? "text-red-700" : "text-slate-600"}`}>{message}</p> : null}
    </div>
  );
}

export function ActionControls({ actionId, status }: { actionId: number; status: string }) {
  const [busy, setBusy] = useState("");
  const terminal = ["rejected", "sent", "dry_run", "failed"].includes(status);

  async function run(operation: "approve" | "reject" | "execute") {
    setBusy(operation);
    try {
      if (operation === "approve") await approveAgentAction(actionId);
      if (operation === "reject") await rejectAgentAction(actionId);
      if (operation === "execute") await executeAgentAction(actionId);
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
        onClick={() => run("execute")}
        disabled={status !== "approved" || busy !== ""}
        className="inline-flex items-center gap-2 border border-teal-700 bg-teal-700 px-3 py-2 text-sm font-semibold text-white disabled:cursor-not-allowed disabled:border-slate-300 disabled:bg-slate-300"
      >
        <Play size={15} />
        {busy === "execute" ? "Executing" : "Execute"}
      </button>
    </div>
  );
}
