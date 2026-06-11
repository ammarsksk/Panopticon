"use client";

import { useEffect, useRef, useState } from "react";
import { Bot, Database, RefreshCw, Save, Send, Square, Trash2, X } from "lucide-react";
import {
  AiIntegrationStatus,
  ChatMessage,
  ChatThread,
  GitLabProject,
  MemoryRecord,
  MemoryRecordUpdate,
  PipelineSnapshot,
  ProjectSummary,
  clearChatHistory,
  deleteChatThread,
  deleteMemoryRecord,
  getChatMessages,
  getMemoryRecords,
  getProjectSummary,
  sendChatMessage,
  updateMemoryRecord
} from "@/lib/api";

function Badge({ label }: { label: string }) {
  return <span className="border border-slate-200 bg-slate-50 px-2 py-1 text-xs font-semibold uppercase text-slate-600">{label}</span>;
}

function PipelineStatus({ status }: { status: string }) {
  const tone = status === "success" ? "border-emerald-200 bg-emerald-50 text-emerald-700" : status === "failed" ? "border-red-200 bg-red-50 text-red-700" : "border-amber-200 bg-amber-50 text-amber-700";
  return <span className={`border px-2 py-0.5 text-[11px] font-semibold uppercase ${tone}`}>{status || "unknown"}</span>;
}

function MessageContent({ content }: { content: string }) {
  const blocks = parseMessageBlocks(content);
  return (
    <div className="space-y-3 text-sm leading-6 text-slate-800">
      {blocks.map((block, index) => {
        if (block.type === "table") {
          return <MarkdownTable key={index} rows={block.rows} />;
        }
        if (block.type === "list") {
          return (
            <ul key={index} className="space-y-1 pl-4">
              {block.items.map((item, itemIndex) => (
                <li key={itemIndex} className="list-disc marker:text-teal-700">
                  {item}
                </li>
              ))}
            </ul>
          );
        }
        if (block.type === "code") {
          return (
            <pre key={index} className="overflow-auto border border-slate-200 bg-slate-950 p-3 text-xs leading-5 text-slate-100">
              <code>{block.text}</code>
            </pre>
          );
        }
        return (
          <p key={index} className="whitespace-pre-wrap">
            {block.text}
          </p>
        );
      })}
    </div>
  );
}

type MessageBlock =
  | { type: "paragraph"; text: string }
  | { type: "code"; text: string }
  | { type: "list"; items: string[] }
  | { type: "table"; rows: string[][] };

function parseMessageBlocks(content: string): MessageBlock[] {
  const lines = content.split(/\r?\n/);
  const blocks: MessageBlock[] = [];
  let index = 0;
  while (index < lines.length) {
    const line = lines[index];
    if (!line.trim()) {
      index += 1;
      continue;
    }
    if (line.trim().startsWith("```")) {
      const code: string[] = [];
      index += 1;
      while (index < lines.length && !lines[index].trim().startsWith("```")) {
        code.push(lines[index]);
        index += 1;
      }
      blocks.push({ type: "code", text: code.join("\n") });
      index += 1;
      continue;
    }
    if (isTableStart(lines, index)) {
      const tableLines: string[] = [];
      while (index < lines.length && looksLikeTableLine(lines[index])) {
        tableLines.push(lines[index]);
        index += 1;
      }
      const rows = tableLines.filter((item) => !isTableSeparator(item)).map(splitTableRow).filter((row) => row.length);
      if (rows.length) blocks.push({ type: "table", rows });
      continue;
    }
    if (/^\s*[-*]\s+/.test(line)) {
      const items: string[] = [];
      while (index < lines.length && /^\s*[-*]\s+/.test(lines[index])) {
        items.push(lines[index].replace(/^\s*[-*]\s+/, "").trim());
        index += 1;
      }
      blocks.push({ type: "list", items });
      continue;
    }
    const paragraph: string[] = [];
    while (
      index < lines.length &&
      lines[index].trim() &&
      !lines[index].trim().startsWith("```") &&
      !isTableStart(lines, index) &&
      !/^\s*[-*]\s+/.test(lines[index])
    ) {
      paragraph.push(lines[index]);
      index += 1;
    }
    blocks.push({ type: "paragraph", text: paragraph.join("\n") });
  }
  return blocks.length ? blocks : [{ type: "paragraph", text: content }];
}

function MarkdownTable({ rows }: { rows: string[][] }) {
  const [header, ...body] = rows;
  return (
    <div className="overflow-x-auto border border-slate-200 bg-white shadow-sm">
      <table className="min-w-full border-collapse text-left text-sm">
        <thead className="bg-slate-100 text-xs uppercase tracking-wide text-slate-600">
          <tr>
            {header.map((cell, index) => (
              <th key={index} className="border-b border-slate-200 px-3 py-2 font-semibold">
                {cell}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {body.map((row, rowIndex) => (
            <tr key={rowIndex} className="odd:bg-white even:bg-slate-50">
              {row.map((cell, cellIndex) => (
                <td key={cellIndex} className="border-b border-slate-100 px-3 py-2 align-top text-slate-700">
                  {cell}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function isTableStart(lines: string[], index: number) {
  return looksLikeTableLine(lines[index] || "") && isTableSeparator(lines[index + 1] || "");
}

function looksLikeTableLine(line: string) {
  return line.includes("|") && line.trim().split("|").filter(Boolean).length >= 2;
}

function isTableSeparator(line: string) {
  return /^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)+\|?\s*$/.test(line);
}

function splitTableRow(line: string) {
  return line
    .trim()
    .replace(/^\|/, "")
    .replace(/\|$/, "")
    .split("|")
    .map((cell) => cell.trim());
}

function splitLines(value: string) {
  return value
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean);
}

export function ChatPanel({ projects, threads, aiStatus }: { projects: GitLabProject[]; threads: ChatThread[]; aiStatus: AiIntegrationStatus }) {
  const [projectId, setProjectId] = useState(projects[0]?.id ?? 0);
  const [threadId, setThreadId] = useState<number | undefined>(undefined);
  const [threadList, setThreadList] = useState<ChatThread[]>(threads);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [projectSummary, setProjectSummary] = useState<ProjectSummary | null>(null);
  const [pipelinesLoading, setPipelinesLoading] = useState(false);
  const [preparedActions, setPreparedActions] = useState<number[]>([]);
  const [preparedFixPlans, setPreparedFixPlans] = useState<number[]>([]);
  const [memoryRecords, setMemoryRecords] = useState<MemoryRecord[]>([]);
  const [memoryOpen, setMemoryOpen] = useState(false);
  const [memoryLoading, setMemoryLoading] = useState(false);
  const [memoryError, setMemoryError] = useState("");
  const [editingMemoryId, setEditingMemoryId] = useState<number | null>(null);
  const [memoryDraft, setMemoryDraft] = useState<MemoryRecordUpdate>({});
  const [typingContent, setTypingContent] = useState<Record<number, string>>({});
  const [input, setInput] = useState("Which risks or failures should I look at first?");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const typingTimer = useRef<number | null>(null);
  const abortController = useRef<AbortController | null>(null);

  useEffect(() => {
    setThreadList(threads);
  }, [threads]);

  useEffect(() => {
    if (!threadId) return;
    getChatMessages(threadId)
      .then(setMessages)
      .catch(() => setMessages([]));
  }, [threadId]);

  useEffect(() => {
    loadMemories();
  }, []);

  useEffect(() => {
    if (!projectId) {
      setProjectSummary(null);
      return;
    }
    let cancelled = false;
    setPipelinesLoading(true);
    getProjectSummary(projectId)
      .then((summary) => {
        if (!cancelled) setProjectSummary(summary);
      })
      .catch(() => {
        if (!cancelled) setProjectSummary(null);
      })
      .finally(() => {
        if (!cancelled) setPipelinesLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [projectId]);

  useEffect(() => {
    return () => {
      if (typingTimer.current) window.clearInterval(typingTimer.current);
      abortController.current?.abort();
    };
  }, []);

  function resetCurrentChat() {
    abortController.current?.abort();
    if (typingTimer.current) {
      window.clearInterval(typingTimer.current);
      typingTimer.current = null;
    }
    setThreadId(undefined);
    setMessages([]);
    setPreparedActions([]);
    setPreparedFixPlans([]);
    setTypingContent({});
    setError("");
    setBusy(false);
  }

  async function clearHistory() {
    setError("");
    try {
      await clearChatHistory();
      resetCurrentChat();
      setThreadList([]);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not clear chat history.");
    }
  }

  async function removeThread(id: number) {
    setError("");
    try {
      await deleteChatThread(id);
      if (threadId === id) resetCurrentChat();
      setThreadList((current) => current.filter((thread) => thread.id !== id));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not delete thread.");
    }
  }

  async function loadMemories() {
    setMemoryLoading(true);
    setMemoryError("");
    try {
      setMemoryRecords(await getMemoryRecords(100));
    } catch (err) {
      setMemoryError(err instanceof Error ? err.message : "Could not load memories.");
    } finally {
      setMemoryLoading(false);
    }
  }

  function startMemoryEdit(memory: MemoryRecord) {
    setEditingMemoryId(memory.id);
    setMemoryDraft({
      project_path: memory.project_path,
      memory_type: memory.memory_type,
      signature: memory.signature,
      summary: memory.summary,
      evidence: memory.evidence,
      remediation: memory.remediation
    });
  }

  async function saveMemory(memoryId: number) {
    setMemoryError("");
    try {
      const updated = await updateMemoryRecord(memoryId, {
        ...memoryDraft,
        evidence: Array.isArray(memoryDraft.evidence) ? memoryDraft.evidence : [],
        remediation: Array.isArray(memoryDraft.remediation) ? memoryDraft.remediation : []
      });
      setMemoryRecords((current) => current.map((memory) => (memory.id === memoryId ? updated : memory)));
      setEditingMemoryId(null);
      setMemoryDraft({});
    } catch (err) {
      setMemoryError(err instanceof Error ? err.message : "Could not save memory.");
    }
  }

  async function removeMemory(memoryId: number) {
    setMemoryError("");
    try {
      await deleteMemoryRecord(memoryId);
      setMemoryRecords((current) => current.filter((memory) => memory.id !== memoryId));
      if (editingMemoryId === memoryId) {
        setEditingMemoryId(null);
        setMemoryDraft({});
      }
    } catch (err) {
      setMemoryError(err instanceof Error ? err.message : "Could not delete memory.");
    }
  }

  function startAssistantTyping(message: ChatMessage) {
    if (typingTimer.current) window.clearInterval(typingTimer.current);
    const words = message.content.split(/(\s+)/).filter(Boolean);
    if (!words.length) {
      setBusy(false);
      return;
    }
    let index = 0;
    setTypingContent((current) => ({ ...current, [message.id]: "" }));
    typingTimer.current = window.setInterval(() => {
      index += 1;
      const visible = words.slice(0, index).join("");
      setTypingContent((current) => ({ ...current, [message.id]: visible }));
      if (index >= words.length) {
        if (typingTimer.current) window.clearInterval(typingTimer.current);
        typingTimer.current = null;
        setTypingContent((current) => {
          const next = { ...current };
          delete next[message.id];
          return next;
        });
        setBusy(false);
      }
    }, 35);
  }

  async function submit() {
    const text = input.trim();
    if (!text || busy) return;
    const pendingUserMessage: ChatMessage = {
      id: -Date.now(),
      thread_id: threadId ?? 0,
      role: "user",
      content: text,
      citations: [],
      prepared_action_ids: [],
      created_at: new Date().toISOString()
    };
    const pendingAssistantMessage: ChatMessage = {
      id: pendingUserMessage.id - 1,
      thread_id: threadId ?? 0,
      role: "assistant",
      content: "",
      citations: [],
      prepared_action_ids: [],
      created_at: new Date().toISOString()
    };

    abortController.current?.abort();
    abortController.current = new AbortController();
    setBusy(true);
    setError("");
    setInput("");
    setMessages((current) => [...current, pendingUserMessage, pendingAssistantMessage]);
    try {
      const response = await sendChatMessage(text, projectId || undefined, threadId, abortController.current.signal);
      setThreadId(response.thread.id);
      setThreadList((current) => [response.thread, ...current.filter((thread) => thread.id !== response.thread.id)]);
      setMessages((current) => [...current.filter((message) => message.id !== pendingUserMessage.id && message.id !== pendingAssistantMessage.id), response.user_message, response.assistant_message]);
      setPreparedActions(response.prepared_actions.map((action) => action.id));
      setPreparedFixPlans(response.prepared_fix_plans.map((plan) => plan.id));
      startAssistantTyping(response.assistant_message);
    } catch (err) {
      setMessages((current) => current.filter((message) => message.id !== pendingAssistantMessage.id));
      if (err instanceof DOMException && err.name === "AbortError") {
        setError("Request stopped.");
      } else {
        setError(err instanceof Error ? err.message : "Chat request failed.");
      }
      setBusy(false);
    } finally {
      abortController.current = null;
    }
  }

  function stopResponse() {
    abortController.current?.abort();
    if (typingTimer.current) {
      window.clearInterval(typingTimer.current);
      typingTimer.current = null;
    }
    setTypingContent({});
    setMessages((current) => current.filter((message) => message.content || message.role !== "assistant"));
    setBusy(false);
  }

  function askAboutPipeline(pipeline: PipelineSnapshot) {
    setInput(`Analyze pipeline #${pipeline.pipeline_id} on ${pipeline.ref}. Why did it ${pipeline.status}, what evidence do we have, and what should I inspect next?`);
  }

  return (
    <div className="grid min-h-0 gap-6 lg:grid-cols-[320px_1fr]">
      <aside className="space-y-4 lg:max-h-[calc(100vh-170px)] lg:overflow-y-auto lg:pr-1">
        <div className="border border-slate-200 bg-white p-4">
          <div className="flex items-center justify-between gap-3">
            <div className="text-xs font-semibold uppercase text-slate-500">Project Context</div>
            <button
              type="button"
              onClick={resetCurrentChat}
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
              setPreparedFixPlans([]);
              setTypingContent({});
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
          <div className="flex items-center justify-between gap-3">
            <div className="text-xs font-semibold uppercase text-slate-500">Pipeline Navigator</div>
            <Badge label={projectSummary ? `${projectSummary.latest_pipelines.length}` : projectId ? "Loading" : "Project"} />
          </div>
          {!projectId ? (
            <p className="mt-3 text-sm text-slate-500">Select one project to inspect individual pipelines.</p>
          ) : pipelinesLoading ? (
            <div className="mt-3 flex items-center gap-1 py-2" aria-label="Loading pipelines">
              <span className="h-2 w-2 animate-bounce rounded-full bg-teal-700 [animation-delay:-0.24s]" />
              <span className="h-2 w-2 animate-bounce rounded-full bg-teal-700 [animation-delay:-0.12s]" />
              <span className="h-2 w-2 animate-bounce rounded-full bg-teal-700" />
            </div>
          ) : projectSummary?.latest_pipelines.length ? (
            <div className="mt-3 max-h-80 space-y-2 overflow-y-auto pr-1">
              {projectSummary.latest_pipelines.map((pipeline) => (
                <button
                  key={pipeline.id}
                  type="button"
                  onClick={() => askAboutPipeline(pipeline)}
                  className="block w-full border border-slate-200 bg-slate-50 p-3 text-left transition hover:border-teal-300 hover:bg-teal-50"
                >
                  <div className="flex items-center justify-between gap-2">
                    <span className="text-sm font-semibold text-slate-900">#{pipeline.pipeline_id}</span>
                    <PipelineStatus status={pipeline.status} />
                  </div>
                  <div className="mt-1 truncate text-xs text-slate-600">{pipeline.ref || "no ref"}</div>
                  <div className="mt-2 text-xs font-semibold uppercase text-teal-700">Ask about this pipeline</div>
                </button>
              ))}
            </div>
          ) : (
            <p className="mt-3 text-sm text-slate-500">No synced pipelines for this project yet.</p>
          )}
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
          <div className="flex items-center justify-between gap-3">
            <div className="text-xs font-semibold uppercase text-slate-500">Recent Threads</div>
            {threadList.length ? (
              <button type="button" onClick={clearHistory} className="inline-flex items-center gap-1 text-xs font-semibold uppercase text-red-700 hover:text-red-800">
                <Trash2 size={13} />
                Clear
              </button>
            ) : null}
          </div>
          {threadList.length ? (
            <div className="mt-3 max-h-80 space-y-2 overflow-y-auto pr-1">
              {threadList.slice(0, 8).map((thread) => (
                <div key={thread.id} className="flex items-start gap-2 border border-slate-200 p-2">
                  <button
                    type="button"
                    onClick={() => {
                      setThreadId(thread.id);
                      setProjectId(thread.project_id ?? 0);
                      setPreparedActions([]);
                      setPreparedFixPlans([]);
                      setTypingContent({});
                    }}
                    className="min-w-0 flex-1 text-left text-sm text-slate-700 hover:text-teal-700"
                  >
                    <span className="line-clamp-2">{thread.title}</span>
                  </button>
                  <button type="button" onClick={() => removeThread(thread.id)} className="mt-0.5 text-slate-400 hover:text-red-700" aria-label={`Delete ${thread.title}`}>
                    <X size={14} />
                  </button>
                </div>
              ))}
            </div>
          ) : (
            <p className="mt-2 text-sm text-slate-500">No chat history yet.</p>
          )}
        </div>

        <div className="border border-slate-200 bg-white p-4">
          <div className="flex items-center justify-between gap-3">
            <div className="flex items-center gap-2 text-xs font-semibold uppercase text-slate-500">
              <Database size={15} className="text-teal-700" />
              Chat Memory
            </div>
            <div className="flex items-center gap-2">
              <button type="button" onClick={loadMemories} className="text-slate-500 hover:text-teal-700" aria-label="Refresh memory">
                <RefreshCw size={14} className={memoryLoading ? "animate-spin" : ""} />
              </button>
              <button type="button" onClick={() => setMemoryOpen((current) => !current)} className="text-xs font-semibold uppercase text-teal-700">
                {memoryOpen ? "Hide" : "Show"}
              </button>
            </div>
          </div>
          <p className="mt-2 text-sm text-slate-500">Review and edit the operational memories the agent uses for future answers.</p>
          {memoryError ? <div className="mt-3 border border-red-200 bg-red-50 p-2 text-xs text-red-700">{memoryError}</div> : null}
          {memoryOpen ? (
            <div className="mt-3 max-h-[28rem] space-y-3 overflow-y-auto pr-1">
              {memoryLoading ? (
                <div className="flex items-center gap-1 py-2" aria-label="Loading memories">
                  <span className="h-2 w-2 animate-bounce rounded-full bg-teal-700 [animation-delay:-0.24s]" />
                  <span className="h-2 w-2 animate-bounce rounded-full bg-teal-700 [animation-delay:-0.12s]" />
                  <span className="h-2 w-2 animate-bounce rounded-full bg-teal-700" />
                </div>
              ) : memoryRecords.length ? (
                memoryRecords.map((memory) => {
                  const editing = editingMemoryId === memory.id;
                  return (
                    <div key={memory.id} className="border border-slate-200 bg-slate-50 p-3 text-sm">
                      <div className="flex items-start justify-between gap-2">
                        <div className="min-w-0">
                          <div className="truncate text-xs font-semibold uppercase text-teal-700">{memory.memory_type || "memory"}</div>
                          <div className="truncate text-xs text-slate-500">{memory.project_path || "Workspace-wide"}</div>
                        </div>
                        <div className="flex items-center gap-2">
                          {editing ? (
                            <button type="button" onClick={() => saveMemory(memory.id)} className="text-teal-700 hover:text-teal-900" aria-label="Save memory">
                              <Save size={14} />
                            </button>
                          ) : (
                            <button type="button" onClick={() => startMemoryEdit(memory)} className="text-slate-500 hover:text-teal-700">
                              Edit
                            </button>
                          )}
                          <button type="button" onClick={() => removeMemory(memory.id)} className="text-slate-400 hover:text-red-700" aria-label="Delete memory">
                            <Trash2 size={14} />
                          </button>
                        </div>
                      </div>
                      {editing ? (
                        <div className="mt-3 space-y-2">
                          <input
                            value={memoryDraft.project_path ?? ""}
                            onChange={(event) => setMemoryDraft((current) => ({ ...current, project_path: event.target.value }))}
                            className="w-full border border-slate-300 bg-white p-2 text-xs"
                            placeholder="Project path"
                          />
                          <textarea
                            value={memoryDraft.summary ?? ""}
                            onChange={(event) => setMemoryDraft((current) => ({ ...current, summary: event.target.value }))}
                            className="min-h-20 w-full border border-slate-300 bg-white p-2 text-xs"
                            placeholder="Summary"
                          />
                          <textarea
                            value={(memoryDraft.evidence ?? []).join("\n")}
                            onChange={(event) => setMemoryDraft((current) => ({ ...current, evidence: splitLines(event.target.value) }))}
                            className="min-h-20 w-full border border-slate-300 bg-white p-2 text-xs"
                            placeholder="Evidence, one per line"
                          />
                          <textarea
                            value={(memoryDraft.remediation ?? []).join("\n")}
                            onChange={(event) => setMemoryDraft((current) => ({ ...current, remediation: splitLines(event.target.value) }))}
                            className="min-h-20 w-full border border-slate-300 bg-white p-2 text-xs"
                            placeholder="Remediation, one per line"
                          />
                        </div>
                      ) : (
                        <div className="mt-3 space-y-2 text-slate-700">
                          <p>{memory.summary || "No summary stored."}</p>
                          {memory.evidence.length ? <p className="text-xs text-slate-500">Evidence: {memory.evidence.slice(0, 2).join("; ")}</p> : null}
                          {memory.remediation.length ? <p className="text-xs text-slate-500">Next: {memory.remediation.slice(0, 2).join("; ")}</p> : null}
                        </div>
                      )}
                    </div>
                  );
                })
              ) : (
                <p className="text-sm text-slate-500">No memories stored yet.</p>
              )}
            </div>
          ) : null}
        </div>
      </aside>

      <section className="flex min-h-[calc(100vh-170px)] max-h-[calc(100vh-170px)] flex-col border border-slate-200 bg-white">
        <div className="border-b border-slate-200 p-4">
          <div className="flex items-center gap-2">
            <Bot className="text-teal-700" size={20} />
            <h2 className="font-semibold text-slate-950">Panopticon Chat</h2>
          </div>
          <p className="mt-1 text-sm text-slate-600">Ask about synced GitLab activity, risks, pipelines, incidents, recommendations, memory, or action preparation.</p>
        </div>

        <div className="min-h-0 flex-1 space-y-4 overflow-y-auto p-4">
          {messages.length ? (
            messages.map((message) => (
              <article key={message.id} className={`border p-4 ${message.role === "assistant" ? "border-teal-200 bg-teal-50/40" : "border-slate-200 bg-slate-50"}`}>
                <div className="mb-2 flex items-center justify-between gap-3">
                  <Badge label={message.role} />
                  <span className="text-xs text-slate-500">{new Date(message.created_at).toLocaleString()}</span>
                </div>
                {message.role === "assistant" && !message.content && busy ? (
                  <div className="flex items-center gap-1 py-2" aria-label="Panopticon is thinking">
                    <span className="h-2 w-2 animate-bounce rounded-full bg-teal-700 [animation-delay:-0.24s]" />
                    <span className="h-2 w-2 animate-bounce rounded-full bg-teal-700 [animation-delay:-0.12s]" />
                    <span className="h-2 w-2 animate-bounce rounded-full bg-teal-700" />
                  </div>
                ) : (
                  <MessageContent content={typingContent[message.id] ?? message.content} />
                )}
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
          {preparedFixPlans.length ? (
            <div className="border border-teal-200 bg-teal-50 p-4 text-sm text-teal-800">
              Prepared safe fix plan IDs: {preparedFixPlans.join(", ")}. Review diffs on the Fix Plans page before approving branch or MR creation.
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
              onClick={busy ? stopResponse : submit}
              className={`inline-flex min-w-28 items-center justify-center gap-2 border px-4 py-2 text-sm font-semibold text-white ${
                busy ? "border-red-700 bg-red-700 hover:bg-red-800" : "border-teal-700 bg-teal-700 hover:bg-teal-800"
              }`}
            >
              {busy ? <Square size={16} fill="currentColor" /> : <Send size={16} />}
              {busy ? "Stop" : "Send"}
            </button>
          </div>
        </div>
      </section>
    </div>
  );
}
