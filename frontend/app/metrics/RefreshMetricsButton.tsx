"use client";

import { useState } from "react";
import { RefreshCw } from "lucide-react";
import { refreshMetricSnapshots } from "@/lib/api";

export function RefreshMetricsButton() {
  const [state, setState] = useState<"idle" | "running" | "done" | "failed">("idle");
  const [message, setMessage] = useState("");

  async function refresh() {
    setState("running");
    setMessage("");
    try {
      const snapshots = await refreshMetricSnapshots();
      setState("done");
      setMessage(`Saved ${snapshots.length} metric snapshot${snapshots.length === 1 ? "" : "s"}. Refreshing...`);
      window.setTimeout(() => window.location.reload(), 600);
    } catch (error) {
      setState("failed");
      setMessage(error instanceof Error ? error.message : "Failed to refresh metrics.");
    }
  }

  return (
    <div className="flex flex-col items-start gap-2">
      <button
        type="button"
        onClick={refresh}
        disabled={state === "running"}
        className="inline-flex items-center gap-2 border border-teal-700 bg-teal-700 px-3 py-2 text-sm font-semibold text-white disabled:cursor-not-allowed disabled:border-slate-300 disabled:bg-slate-300"
      >
        <RefreshCw size={16} className={state === "running" ? "animate-spin" : ""} />
        {state === "running" ? "Refreshing Metrics" : "Save Daily Snapshot"}
      </button>
      {message ? <p className={`text-sm ${state === "failed" ? "text-red-700" : "text-slate-600"}`}>{message}</p> : null}
    </div>
  );
}
