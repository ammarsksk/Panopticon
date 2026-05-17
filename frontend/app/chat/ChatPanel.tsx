"use client";

import { useEffect, useState } from "react";
import { Bot, Send } from "lucide-react";
import { AiIntegrationStatus, ChatMessage, ChatThread, GitLabProject, getChatMessages, sendChatMessage } from "@/lib/api";

function Badge({ label }: { label: string }) {
  return <span className="border border-slate-200 bg-slate-50 px-2 py-1 text-xs font-semibold uppercase text-slate-600">{label}</span>;
}

export function ChatPanel({ projects, threads, aiStatus }: { projects: GitLabProject[]; threads: ChatThread[]; aiStatus: AiIntegrationStatus }) {
  const [projectId, setProjectId] = useState(projects[0]?.id ?? 0);
  const [threadId, setThreadId] = useState<number | undefined>(undefined);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [preparedActions, setPreparedActions] = useState<number[]>([]);
  const [input, setInput] = useState("Which risks or failures should I look at first?");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!threadId) return;
    getChatMessages(threadId)
      .then(setMessages)
      .catch(() => setMessages([]));
  }, [threadId]);

  async function submit() {
    const text = input.trim();
    if (!text || busy) return;
    setBusy(true);
    setError("");
    try {
      const response = await sendChatMessage(text, projectId || undefined, threadId);
      setThreadId(response.thread.id);
      setMessages((current) => [...current, response.user_message, response.assistant_message]);
      setPreparedActions(response.prepared_actions.map((action) => action.id));
      setInput("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Chat request failed.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="grid gap-6 lg:grid-cols-[320px_1fr]">
      <aside className="space-y-4">
        <div className="border border-slate-200 bg-white p-4">
          <div className="flex items-center justify-between gap-3">
            <div className="text-xs font-semibold uppercase text-slate-500">Project Context</div>
            <button
              type="button"
              onClick={() => {
                setThreadId(undefined);
                setMessages([]);
                setPreparedActions([]);
              }}
              className="text-xs font-semibold uppercase text-teal-700"
            >
              New Chat
            </button>
          </div>
          <select
            value={projectId}
            onChange={(event) => {
              setProjectId(Number(event.target.value));
              setThreadId(undefined);
              setMessages([]);
            }}
            className="mt-2 w-full border border-slate-300 bg-white p-2 text-sm"
          >
            <option value={0}>All synced projects</option>
            {projects.map((project) => (
              <option key={project.id} value={project.id}>
                {project.project_path}
              </option>
            ))}
          </select>
        </div>

        <div className="border border-slate-200 bg-white p-4">
          <div className="text-xs font-semibold uppercase text-slate-500">AI Runtime</div>
          <div className="mt-3 space-y-2 text-sm text-slate-700">
            <div className="flex items-center justify-between gap-3">
              <span>Chat mode</span>
              <Badge label={aiStatus.chat_mode === "vertex_gemini" ? "Vertex Gemini" : "Fallback"} />
            </div>
            <div className="flex items-center justify-between gap-3">
              <span>Model</span>
              <span className="text-right text-xs font-semibold text-slate-600">{aiStatus.model}</span>
            </div>
            <div className="flex items-center justify-between gap-3">
              <span>Tool layer</span>
              <span className="text-right text-xs font-semibold text-slate-600">{aiStatus.tool_layer}</span>
            </div>
            <div className="flex items-center justify-between gap-3">
              <span>MCP</span>
              <Badge label={aiStatus.mcp_enabled ? "Connected" : "Not connected"} />
            </div>
          </div>
        </div>

        <div className="border border-slate-200 bg-white p-4">
          <div className="text-xs font-semibold uppercase text-slate-500">Recent Threads</div>
          {threads.length ? (
            <div className="mt-3 space-y-2">
              {threads.slice(0, 8).map((thread) => (
                <button
                  key={thread.id}
                  type="button"
                  onClick={() => {
                    setThreadId(thread.id);
                    setProjectId(thread.project_id ?? 0);
                    setPreparedActions([]);
                  }}
                  className="block w-full border border-slate-200 p-2 text-left text-sm text-slate-700"
                >
                  {thread.title}
                </button>
              ))}
            </div>
          ) : (
            <p className="mt-2 text-sm text-slate-500">No chat history yet.</p>
          )}
        </div>
      </aside>

      <section className="border border-slate-200 bg-white">
        <div className="border-b border-slate-200 p-4">
          <div className="flex items-center gap-2">
            <Bot className="text-teal-700" size={20} />
            <h2 className="font-semibold text-slate-950">Panopticon Chat</h2>
          </div>
          <p className="mt-1 text-sm text-slate-600">Ask about synced GitLab activity, risks, pipelines, incidents, recommendations, memory, or action preparation.</p>
        </div>

        <div className="min-h-[420px] space-y-4 p-4">
          {messages.length ? (
            messages.map((message) => (
              <article key={message.id} className={`border p-4 ${message.role === "assistant" ? "border-teal-200 bg-teal-50/40" : "border-slate-200 bg-slate-50"}`}>
                <div className="mb-2 flex items-center justify-between gap-3">
                  <Badge label={message.role} />
                  <span className="text-xs text-slate-500">{new Date(message.created_at).toLocaleString()}</span>
                </div>
                <p className="whitespace-pre-line text-sm leading-6 text-slate-800">{message.content}</p>
                {message.citations.length ? (
                  <div className="mt-4">
                    <div className="text-xs font-semibold uppercase text-slate-500">Citations</div>
                    <div className="mt-2 grid gap-2 md:grid-cols-2">
                      {message.citations.map((citation) => (
                        <div key={`${citation.type}-${citation.id}`} className="border border-slate-200 bg-white p-2 text-xs text-slate-600">
                          <div className="font-semibold text-slate-800">{citation.type} #{citation.id}</div>
                          <div>{citation.label}</div>
                          {citation.summary ? <div className="mt-1 text-slate-500">{citation.summary}</div> : null}
                        </div>
                      ))}
                    </div>
                  </div>
                ) : null}
              </article>
            ))
          ) : (
            <div className="border border-dashed border-slate-300 p-6 text-sm leading-6 text-slate-600">
              Try: "Why is this project risky?", "What changed before the failure?", or "Prepare actions for this project."
            </div>
          )}

          {preparedActions.length ? (
            <div className="border border-amber-200 bg-amber-50 p-4 text-sm text-amber-800">
              Prepared action IDs: {preparedActions.join(", ")}. Review them on the Actions page before execution.
            </div>
          ) : null}
          {error ? <div className="border border-red-200 bg-red-50 p-3 text-sm text-red-700">{error}</div> : null}
        </div>

        <div className="border-t border-slate-200 p-4">
          <div className="flex gap-2">
            <textarea
              value={input}
              onChange={(event) => setInput(event.target.value)}
              className="min-h-20 flex-1 border border-slate-300 p-3 text-sm"
              placeholder="Ask Panopticon..."
            />
            <button
              type="button"
              onClick={submit}
              disabled={busy}
              className="inline-flex items-center gap-2 border border-teal-700 bg-teal-700 px-4 py-2 text-sm font-semibold text-white disabled:cursor-not-allowed disabled:border-slate-300 disabled:bg-slate-300"
            >
              <Send size={16} />
              {busy ? "Sending" : "Send"}
            </button>
          </div>
        </div>
      </section>
    </div>
  );
}
