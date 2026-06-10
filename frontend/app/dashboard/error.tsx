"use client";

import Link from "next/link";
import { RefreshCw, ShieldAlert } from "lucide-react";

export default function DashboardError({ error, reset }: { error: Error & { digest?: string }; reset: () => void }) {
  const message = error?.message || "";
  const isAuth = message.includes("(401)");

  return (
    <main className="min-h-screen bg-[var(--background)] px-6 py-16 text-slate-950">
      <section className="mx-auto max-w-xl border border-slate-200 bg-white p-6 shadow-sm">
        <div className="flex items-center gap-2 text-sm font-semibold uppercase text-teal-700">
          <ShieldAlert size={18} aria-hidden="true" />
          Dashboard unavailable
        </div>
        <h1 className="mt-3 text-2xl font-semibold">{isAuth ? "Sign in to open the console" : "Could not load dashboard data"}</h1>
        <p className="mt-2 text-sm leading-6 text-slate-600">
          {isAuth
            ? "The backend requires an authenticated workspace session before it can load dashboard data."
            : "The backend is running, but one of the dashboard API calls failed. Retry after checking the backend logs."}
        </p>
        <div className="mt-5 flex flex-wrap gap-2">
          <Link href="/login" className="inline-flex items-center gap-2 border border-teal-700 bg-teal-700 px-3 py-2 text-sm font-semibold text-white">
            Sign in
          </Link>
          <button type="button" onClick={() => reset()} className="inline-flex items-center gap-2 border border-slate-300 bg-white px-3 py-2 text-sm font-semibold text-slate-700">
            <RefreshCw size={15} aria-hidden="true" />
            Retry
          </button>
        </div>
      </section>
    </main>
  );
}
