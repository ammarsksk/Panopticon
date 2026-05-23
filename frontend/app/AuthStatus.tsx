"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { LogOut, UserCircle } from "lucide-react";
import { AuthSession, getAuthSession, logout } from "@/lib/api";

export function AuthStatus() {
  const [session, setSession] = useState<AuthSession | null>(null);

  useEffect(() => {
    getAuthSession().then(setSession).catch(() => setSession(null));
  }, []);

  async function signOut() {
    await logout().catch(() => null);
    window.location.href = "/login";
  }

  if (!session) {
    return (
      <Link href="/login" className="fixed bottom-[72px] right-5 z-50 inline-flex items-center gap-2 border border-slate-300 bg-white px-3 py-2 text-xs font-semibold text-slate-700 shadow-sm">
        <UserCircle size={15} aria-hidden="true" />
        Sign in
      </Link>
    );
  }

  return (
    <div className="fixed bottom-[72px] right-5 z-50 hidden items-center gap-2 border border-slate-200 bg-white px-3 py-2 text-xs font-semibold text-slate-700 shadow-sm sm:inline-flex">
      <UserCircle size={15} aria-hidden="true" />
      <span>{session.workspace.name}</span>
      {session.auth_required ? (
        <button type="button" onClick={signOut} className="inline-flex items-center gap-1 text-slate-500 hover:text-teal-700" title="Sign out">
          <LogOut size={14} aria-hidden="true" />
          <span className="sr-only">Sign out</span>
        </button>
      ) : null}
    </div>
  );
}
