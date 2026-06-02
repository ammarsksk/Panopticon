"use client";

import { useState } from "react";
import { RefreshCw } from "lucide-react";
import { syncGitLabProjects } from "@/lib/api";

export function SyncProjectsButton() {
  const [state, setState] = useState<"idle" | "syncing" | "completed" | "failed">("idle");
  const [message, setMessage] = useState("");

  async function runSync() {
    setState("syncing");
    setMessage("");
    try {
      const result = await syncGitLabProjects();
      if (result.status === "completed" || result.status === "completed_with_errors") {
        setState("completed");
        setMessage(
          result.projects_updated
            ? `Synced ${result.projects_updated} project${result.projects_updated === 1 ? "" : "s"}. Refreshing...`
            : result.error || "GitLab returned no accessible projects. Refreshing..."
        );
        window.setTimeout(() => window.location.reload(), 700);
      } else {
        setState("failed");
        setMessage(result.error || "GitLab sync did not complete.");
      }
    } catch (error) {
      setState("failed");
      setMessage(error instanceof Error ? error.message : "GitLab sync failed.");
    }
  }

  return (
    <div className="flex flex-col items-start gap-2">
      <button
        type="button"
        onClick={runSync}
        disabled={state === "syncing"}
        className="inline-flex items-center gap-2 border border-teal-700 bg-teal-700 px-3 py-2 text-sm font-semibold text-white disabled:cursor-not-allowed disabled:border-slate-300 disabled:bg-slate-300"
      >
        <RefreshCw size={16} className={state === "syncing" ? "animate-spin" : ""} />
        {state === "syncing" ? "Syncing GitLab" : "Sync GitLab Projects"}
      </button>
      {message ? (
        <p className={`text-sm ${state === "failed" ? "text-red-700" : "text-slate-600"}`}>{message}</p>
      ) : null}
    </div>
  );
}
