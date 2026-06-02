"use client";

import { useState, useTransition } from "react";
import { RefreshCw } from "lucide-react";
import { refreshRepoIndex, RepoIndexRun } from "@/lib/api";

export function RepoIndexButton({ projectId }: { projectId: string }) {
  const [isPending, startTransition] = useTransition();
  const [run, setRun] = useState<RepoIndexRun | null>(null);
  const [error, setError] = useState("");

  function refresh() {
    setError("");
    startTransition(async () => {
      try {
        const nextRun = await refreshRepoIndex(projectId);
        setRun(nextRun);
      } catch {
        setError("Repo indexing failed. Confirm GitLab is connected with repository access, then try again.");
      }
    });
  }

  return (
    <div className="flex flex-wrap items-center gap-3">
      <button
        type="button"
        onClick={refresh}
        disabled={isPending}
        className="inline-flex items-center gap-2 border border-teal-200 bg-teal-50 px-3 py-2 text-sm font-semibold text-teal-800 transition hover:-translate-y-0.5 hover:border-teal-300 hover:bg-teal-100 disabled:cursor-not-allowed disabled:opacity-60"
      >
        <RefreshCw size={14} className={isPending ? "animate-spin" : ""} />
        {isPending ? "Indexing repository" : "Refresh repo context"}
      </button>
      {run ? <span className="text-sm text-slate-600">Indexed {run.files_indexed} file(s); skipped {run.files_skipped}.</span> : null}
      {error ? <span className="text-sm text-red-700">{error}</span> : null}
    </div>
  );
}
