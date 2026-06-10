"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { LogOut, UserCircle } from "lucide-react";
import { AuthSession, getAuthSession, logout } from "@/lib/api";

export function AuthStatus() {
  const [session, setSession] = useState<AuthSession | null>(null);
  const pathname = usePathname();
  const hideFloatingStatus = pathname === "/" || pathname === "/login" || pathname === "/signup";

  useEffect(() => {
    getAuthSession().then(setSession).catch(() => setSession(null));
  }, []);

  async function signOut() {
    await logout().catch(() => null);
    window.location.href = "/login";
  }

  if (hideFloatingStatus) return null;

  if (!session) {
    return (
      <Link href="/login" className="auth-status inline-flex items-center gap-2 border border-slate-300 bg-white px-3 py-2 text-xs font-semibold text-slate-700 shadow-sm">
        <img src="/panopticon-logo.png" alt="" width={18} height={18} className="h-[18px] w-[18px] shrink-0 object-contain" />
        Sign in
      </Link>
    );
  }

  return (
    <div className="auth-status group inline-flex max-w-[calc(100vw-36px)] items-center gap-2 border border-slate-200 bg-white px-3 py-2 text-xs font-semibold text-slate-700 shadow-sm">
      <img src="/panopticon-logo.png" alt="" width={18} height={18} className="h-[18px] w-[18px] shrink-0 object-contain" />
      <UserCircle size={15} aria-hidden="true" />
      <span className="min-w-0 truncate">{session.workspace.name}</span>
      {session.auth_required ? (
        <button type="button" onClick={signOut} className="auth-status-signout inline-flex shrink-0 items-center gap-1 border-l border-slate-200 px-2 py-1 text-slate-500" title="Sign out">
          <LogOut size={14} aria-hidden="true" />
          <span>Sign out</span>
        </button>
      ) : null}
    </div>
  );
}
