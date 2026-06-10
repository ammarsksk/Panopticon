"use client";

import { FormEvent, useEffect, useState } from "react";
import Link from "next/link";
import { LayoutDashboard, LogIn, LogOut, UserPlus } from "lucide-react";
import { API_BASE, AuthSession, getAuthSession, login, logout, signup } from "@/lib/api";

type Mode = "login" | "signup";

export function AuthForm({ mode }: { mode: Mode }) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [name, setName] = useState("");
  const [workspaceName, setWorkspaceName] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [session, setSession] = useState<AuthSession | null>(null);
  const [checkingSession, setCheckingSession] = useState(true);
  const isSignup = mode === "signup";

  useEffect(() => {
    getAuthSession()
      .then((currentSession) => {
        setSession(currentSession);
        window.location.replace("/dashboard");
      })
      .catch(() => setSession(null))
      .finally(() => setCheckingSession(false));
  }, []);

  async function signOut() {
    setBusy(true);
    setError("");
    try {
      await logout();
      setSession(null);
    } catch {
      setError("Could not sign out. Restart the backend and try again.");
    } finally {
      setBusy(false);
    }
  }

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
      setSession(await getAuthSession());
      window.location.replace("/dashboard");
    } catch (error) {
      setError(isSignup ? "Could not create the account. Use a valid email and an 8+ character password." : signInErrorMessage(error));
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
          <div className="mt-3 flex items-center gap-3">
            <img src="/panopticon-logo.png" alt="" width={32} height={32} className="h-8 w-8 shrink-0 object-contain" />
            <h1 className="text-2xl font-semibold">Panopticon</h1>
          </div>
          <p className="mt-2 text-sm leading-6 text-slate-600">
            {isSignup ? "Create your user and isolated workspace for GitLab operations data." : "Sign in to your Panopticon workspace."}
          </p>

          {error && session ? <div className="mt-4 border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">{error}</div> : null}

          {checkingSession ? (
            <div className="mt-6 border border-slate-200 bg-slate-50 px-4 py-3 text-sm text-slate-600">Checking current session...</div>
          ) : session ? (
            <div className="mt-6 border border-teal-200 bg-teal-50 p-4">
              <div className="text-sm font-semibold text-teal-800">Already signed in</div>
              <p className="mt-2 text-sm leading-6 text-slate-700">
                You are signed in as {session.user.email} in {session.workspace.name}. Open the dashboard or sign out to use another account.
              </p>
              <div className="mt-4 flex flex-wrap gap-2">
                <Link href="/dashboard" className="inline-flex items-center gap-2 border border-teal-700 bg-teal-700 px-3 py-2 text-sm font-semibold text-white">
                  <LayoutDashboard size={16} aria-hidden="true" />
                  Open dashboard
                </Link>
                {session.auth_required ? (
                  <button type="button" onClick={signOut} disabled={busy} className="inline-flex items-center gap-2 border border-red-200 bg-white px-3 py-2 text-sm font-semibold text-red-700 hover:border-red-500 hover:bg-red-50 disabled:cursor-not-allowed disabled:opacity-60">
                    <LogOut size={16} aria-hidden="true" />
                    Sign out
                  </button>
                ) : null}
              </div>
            </div>
          ) : (
            <>
              <a
                href={`${API_BASE}/api/auth/google/start?redirect_after=${encodeURIComponent("/dashboard")}`}
                className="mt-6 inline-flex w-full items-center justify-center gap-2 border border-slate-300 bg-white px-4 py-2 text-sm font-semibold text-slate-800 transition hover:border-teal-500 hover:text-teal-700"
              >
                <GoogleLogo />
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
            </>
          )}

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

function signInErrorMessage(error: unknown) {
  if (error && typeof error === "object" && "status" in error) {
    const status = (error as { status?: unknown }).status;
    if (status === 403) return "The secure sign-in token expired. Reload the page and try again.";
    if (status === 401) return "Invalid email or password.";
    return `Sign in failed with API status ${status}.`;
  }
  return "Invalid email or password.";
}

function GoogleLogo() {
  return (
    <svg width="18" height="18" viewBox="0 0 18 18" aria-hidden="true" focusable="false">
      <path fill="#4285F4" d="M17.64 9.2c0-.64-.06-1.25-.16-1.84H9v3.48h4.84a4.14 4.14 0 0 1-1.8 2.72v2.26h2.91c1.7-1.57 2.69-3.88 2.69-6.62Z" />
      <path fill="#34A853" d="M9 18c2.43 0 4.47-.8 5.96-2.18l-2.91-2.26c-.8.54-1.84.86-3.05.86-2.34 0-4.33-1.58-5.04-3.71H.96v2.33A9 9 0 0 0 9 18Z" />
      <path fill="#FBBC05" d="M3.96 10.71a5.41 5.41 0 0 1 0-3.42V4.96H.96a9 9 0 0 0 0 8.08l3-2.33Z" />
      <path fill="#EA4335" d="M9 3.58c1.32 0 2.51.45 3.44 1.35l2.58-2.58C13.46.9 11.43 0 9 0A9 9 0 0 0 .96 4.96l3 2.33C4.67 5.16 6.66 3.58 9 3.58Z" />
    </svg>
  );
}
