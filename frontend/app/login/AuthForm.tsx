"use client";

import { FormEvent, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { Chrome, LogIn, UserPlus } from "lucide-react";
import { API_BASE, login, signup } from "@/lib/api";

type Mode = "login" | "signup";

export function AuthForm({ mode }: { mode: Mode }) {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [name, setName] = useState("");
  const [workspaceName, setWorkspaceName] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const isSignup = mode === "signup";

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError("");
    setBusy(true);
    try {
      if (isSignup) {
        await signup(email, password, name, workspaceName);
      } else {
        await login(email, password);
      }
      router.push("/");
      router.refresh();
    } catch {
      setError(isSignup ? "Could not create the account. Use a valid email and an 8+ character password." : "Invalid email or password.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="min-h-screen bg-slate-50 text-slate-950">
      <div className="mx-auto flex min-h-screen max-w-md items-center px-6 py-10">
        <section className="w-full border border-slate-200 bg-white p-6">
          <div className="flex items-center gap-2 text-sm font-semibold uppercase text-teal-700">
            {isSignup ? <UserPlus size={17} aria-hidden="true" /> : <LogIn size={17} aria-hidden="true" />}
            {isSignup ? "Create Workspace" : "Sign In"}
          </div>
          <h1 className="mt-3 text-2xl font-semibold">Panopticon</h1>
          <p className="mt-2 text-sm leading-6 text-slate-600">
            {isSignup ? "Create your user and isolated workspace for GitLab operations data." : "Sign in to your Panopticon workspace."}
          </p>

          <a
            href={`${API_BASE}/api/auth/google/start`}
            className="mt-6 inline-flex w-full items-center justify-center gap-2 border border-slate-300 bg-white px-4 py-2 text-sm font-semibold text-slate-800 transition hover:border-teal-500 hover:text-teal-700"
          >
            <Chrome size={16} aria-hidden="true" />
            Continue with Google
          </a>

          <div className="my-5 flex items-center gap-3 text-xs font-semibold uppercase text-slate-400">
            <span className="h-px flex-1 bg-slate-200" />
            or
            <span className="h-px flex-1 bg-slate-200" />
          </div>

          <form onSubmit={submit} className="space-y-4">
            {isSignup ? (
              <>
                <label className="block">
                  <span className="text-sm font-medium text-slate-700">Name</span>
                  <input value={name} onChange={(event) => setName(event.target.value)} className="mt-1 w-full border border-slate-300 bg-white px-3 py-2 text-sm" />
                </label>
                <label className="block">
                  <span className="text-sm font-medium text-slate-700">Workspace name</span>
                  <input value={workspaceName} onChange={(event) => setWorkspaceName(event.target.value)} className="mt-1 w-full border border-slate-300 bg-white px-3 py-2 text-sm" />
                </label>
              </>
            ) : null}

            <label className="block">
              <span className="text-sm font-medium text-slate-700">Email</span>
              <input type="email" required value={email} onChange={(event) => setEmail(event.target.value)} className="mt-1 w-full border border-slate-300 bg-white px-3 py-2 text-sm" />
            </label>
            <label className="block">
              <span className="text-sm font-medium text-slate-700">Password</span>
              <input type="password" required minLength={8} value={password} onChange={(event) => setPassword(event.target.value)} className="mt-1 w-full border border-slate-300 bg-white px-3 py-2 text-sm" />
            </label>

            {error ? <div className="border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">{error}</div> : null}

            <button type="submit" disabled={busy} className="inline-flex w-full items-center justify-center gap-2 border border-teal-700 bg-teal-700 px-4 py-2 text-sm font-semibold text-white disabled:cursor-not-allowed disabled:border-slate-300 disabled:bg-slate-300">
              {isSignup ? <UserPlus size={16} aria-hidden="true" /> : <LogIn size={16} aria-hidden="true" />}
              {busy ? "Working..." : isSignup ? "Create account" : "Sign in"}
            </button>
          </form>

          <div className="mt-5 text-sm text-slate-600">
            {isSignup ? (
              <>
                Already have an account? <Link href="/login" className="font-semibold text-teal-700">Sign in</Link>
              </>
            ) : (
              <>
                New workspace? <Link href="/signup" className="font-semibold text-teal-700">Create one</Link>
              </>
            )}
          </div>
        </section>
      </div>
    </main>
  );
}
