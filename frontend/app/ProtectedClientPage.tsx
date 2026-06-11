"use client";

import { ReactNode, useEffect, useState } from "react";
import Link from "next/link";
import { AlertTriangle, Loader2, LogIn, RefreshCw } from "lucide-react";
import { isUnauthorized } from "@/lib/api";

export function ProtectedClientPage<T>({
  load,
  children,
  title = "Opening workspace",
  loadingText = "Loading your workspace from the authenticated browser session..."
}: {
  load: () => Promise<T>;
  children: (data: T) => ReactNode;
  title?: string;
  loadingText?: string;
}) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;

    async function run() {
      setLoading(true);
      setError("");
      try {
        const nextData = await load();
        if (!cancelled) setData(nextData);
      } catch (error) {
        if (cancelled) return;
        if (isUnauthorized(error)) {
          window.location.replace("/login");
          return;
        }
        setError(error instanceof Error ? error.message : "The workspace data could not be loaded.");
      } finally {
        if (!cancelled) setLoading(false);
      }
    }

    run();
    return () => {
      cancelled = true;
    };
    // This intentionally runs once per page mount. The load function is page-local.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  if (data) return <>{children(data)}</>;

  return (
    <main className="min-h-screen bg-slate-50 text-slate-950">
      <div className="mx-auto flex min-h-screen max-w-2xl items-center px-6 py-10">
        <section className="w-full border border-slate-200 bg-white p-6 shadow-sm">
          <div className="flex items-center gap-3">
            <img src="/panopticon-logo.png" alt="" width={32} height={32} className="h-8 w-8 shrink-0 object-contain" />
            <div>
              <div className="text-sm font-semibold uppercase text-teal-700">Panopticon</div>
              <h1 className="text-2xl font-semibold">{title}</h1>
            </div>
          </div>

          {loading ? (
            <div className="mt-6 flex items-center gap-3 border border-slate-200 bg-slate-50 px-4 py-3 text-sm text-slate-600">
              <Loader2 size={18} className="animate-spin text-teal-700" aria-hidden="true" />
              {loadingText}
            </div>
          ) : error ? (
            <div className="mt-6 border border-red-200 bg-red-50 p-4">
              <div className="flex items-center gap-2 font-semibold text-red-700">
                <AlertTriangle size={18} aria-hidden="true" />
                Workspace unavailable
              </div>
              <p className="mt-2 text-sm leading-6 text-red-700">{error}</p>
              <div className="mt-4 flex flex-wrap gap-2">
                <button
                  type="button"
                  onClick={() => window.location.reload()}
                  className="inline-flex items-center gap-2 border border-red-300 bg-white px-3 py-2 text-sm font-semibold text-red-700 transition hover:border-red-500 hover:bg-red-100"
                >
                  <RefreshCw size={16} aria-hidden="true" />
                  Retry
                </button>
                <Link href="/login" className="inline-flex items-center gap-2 border border-slate-300 bg-white px-3 py-2 text-sm font-semibold text-slate-700 transition hover:border-teal-500 hover:text-teal-700">
                  <LogIn size={16} aria-hidden="true" />
                  Sign in again
                </Link>
              </div>
            </div>
          ) : null}
        </section>
      </div>
    </main>
  );
}
