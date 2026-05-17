import Link from "next/link";
import { ArrowLeft, MessageSquareText } from "lucide-react";
import { getAiIntegrationStatus, getChatThreads, getProjectsData } from "@/lib/api";
import { ChatPanel } from "./ChatPanel";

export default async function ChatPage() {
  const [{ projects }, threads, aiStatus] = await Promise.all([getProjectsData(), getChatThreads(), getAiIntegrationStatus()]);

  return (
    <main className="min-h-screen bg-slate-50 text-slate-950">
      <header className="border-b border-slate-200 bg-white">
        <div className="mx-auto max-w-7xl px-6 py-5">
          <Link href="/" className="mb-3 inline-flex items-center gap-2 text-sm font-medium text-teal-700">
            <ArrowLeft size={16} />
            Dashboard
          </Link>
          <div className="flex items-center gap-2">
            <MessageSquareText className="text-teal-700" size={24} />
            <h1 className="text-2xl font-semibold">Chat</h1>
          </div>
          <p className="mt-1 text-sm text-slate-600">Ask grounded questions about GitLab operations data stored in Panopticon.</p>
        </div>
      </header>
      <div className="mx-auto max-w-7xl px-6 py-6">
        <ChatPanel projects={projects} threads={threads} aiStatus={aiStatus} />
      </div>
    </main>
  );
}
