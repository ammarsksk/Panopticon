"use client";

import Link from "next/link";
import { type CSSProperties, useEffect, useMemo, useState } from "react";
import {
  Activity,
  ArrowRight,
  Bot,
  CircleDot,
  ClipboardCheck,
  Code2,
  GitBranch,
  GitPullRequest,
  LockKeyhole,
  MessageSquare,
  Play,
  RadioTower,
  ShieldCheck,
  Sparkles,
  TerminalSquare,
  Zap
} from "lucide-react";

const signalCards = [
  {
    label: "Pipeline failure",
    title: "Deploy job timed out",
    detail: "Panopticon ties the failed job trace to deployment and payment gateway changes.",
    response: "Inspect deploy-production, validate rollout readiness, then approve the Slack alert only if the payload matches the evidence.",
    tone: "warn"
  },
  {
    label: "Risky merge request",
    title: "Auth and infra touched together",
    detail: "The agent detects sensitive code paths, deployment files, and missing tests in the same change.",
    response: "Require owner review, add focused auth coverage, and prepare a GitLab comment draft for approval.",
    tone: "critical"
  },
  {
    label: "Safe fix plan",
    title: "Generate reviewable remediation",
    detail: "Fix plans create branches and merge requests only after human approval.",
    response: "Prepare a branch plan with diff previews, validation commands, rollback notes, and approval history.",
    tone: "good"
  }
];

const workflow = [
  { icon: GitBranch, title: "Connect GitLab", detail: "Sync projects, merge requests, pipelines, failed jobs, and repository context." },
  { icon: Bot, title: "Ask the agent", detail: "Query failures, risky releases, incidents, code paths, and prior operational memory." },
  { icon: ClipboardCheck, title: "Review evidence", detail: "Every recommendation stays grounded in synced records, job traces, files, and memory." },
  { icon: GitPullRequest, title: "Approve changes", detail: "Slack alerts, GitLab comments, branches, and MRs stay approval-gated." }
];

const capabilities = [
  { icon: MessageSquare, title: "Agentic chat", detail: "Ask for tables, checklists, root-cause summaries, action drafts, or safe fix plans." },
  { icon: TerminalSquare, title: "MCP tool layer", detail: "The agent retrieves project, pipeline, risk, memory, and repo context through explicit tools." },
  { icon: Code2, title: "Code-change plans", detail: "Generate diff previews, test commands, and rollback notes before touching GitLab." },
  { icon: ShieldCheck, title: "Production guardrails", detail: "Secret redaction, approval safety, workspace isolation, and answer validation are built in." }
];

export function LandingPage() {
  const [activeSignal, setActiveSignal] = useState(0);
  const [pointer, setPointer] = useState({ x: 0, y: 0 });
  const selected = signalCards[activeSignal];

  useEffect(() => {
    const elements = Array.from(document.querySelectorAll<HTMLElement>(".landing-reveal"));
    const observer = new IntersectionObserver(
      (entries) => {
        entries.forEach((entry) => {
          if (entry.isIntersecting) entry.target.classList.add("is-visible");
        });
      },
      { threshold: 0.16 }
    );
    elements.forEach((element) => observer.observe(element));
    return () => observer.disconnect();
  }, []);

  const sceneStyle = useMemo(
    () => ({
      "--tilt-x": `${pointer.y * -5}deg`,
      "--tilt-y": `${pointer.x * 6}deg`
    }) as CSSProperties,
    [pointer]
  );

  return (
    <main className="landing-shell min-h-screen bg-[var(--background)] text-slate-950">
      <header className="landing-nav">
        <Link href="/" className="landing-brand" aria-label="Panopticon home">
          <img src="/panopticon-logo.png" alt="" width={30} height={30} className="landing-logo landing-logo-sm" />
          <span>Panopticon</span>
        </Link>
        <nav className="landing-nav-links" aria-label="Landing navigation">
          <a href="#workflow">Workflow</a>
          <a href="#agent">Agent</a>
          <a href="#security">Security</a>
          <Link href="/dashboard">Console</Link>
        </nav>
        <div className="landing-nav-actions">
          <Link href="/login" className="landing-link-button">
            Sign in
          </Link>
          <Link href="/signup" className="landing-primary-button">
            Start workspace
            <ArrowRight size={16} aria-hidden="true" />
          </Link>
        </div>
      </header>

      <section
        className="landing-hero"
        onMouseMove={(event) => {
          const rect = event.currentTarget.getBoundingClientRect();
          setPointer({
            x: (event.clientX - rect.left) / rect.width - 0.5,
            y: (event.clientY - rect.top) / rect.height - 0.5
          });
        }}
        onMouseLeave={() => setPointer({ x: 0, y: 0 })}
      >
        <div className="landing-grid" aria-hidden="true" />
        <div className="landing-hero-scene" style={sceneStyle} aria-hidden="true">
          <div className="landing-console landing-console-main">
            <div className="landing-console-top">
              <span className="landing-dot landing-dot-red" />
              <span className="landing-dot landing-dot-amber" />
              <span className="landing-dot landing-dot-green" />
              <span className="landing-console-title">agent runtime</span>
            </div>
            <div className="landing-console-body">
              <div className="landing-stream-row">
                <span className="landing-stream-label">risk</span>
                <span>checkout-core deployment scored 91/100</span>
              </div>
              <div className="landing-stream-row">
                <span className="landing-stream-label">job</span>
                <span>deploy-production failed after rollout wait</span>
              </div>
              <div className="landing-stream-row">
                <span className="landing-stream-label">repo</span>
                <span>auth.py, payment_gateway.py, deployment.yaml</span>
              </div>
              <div className="landing-agent-answer">
                <Sparkles size={15} aria-hidden="true" />
                Prepare a Slack alert and GitLab comment draft. Approval required before execution.
              </div>
            </div>
          </div>
          <div className="landing-console landing-console-side">
            <div className="landing-signal-pill">
              <Zap size={14} aria-hidden="true" />
              live evidence
            </div>
            <div className="landing-mini-bars">
              <span style={{ width: "82%" }} />
              <span style={{ width: "58%" }} />
              <span style={{ width: "71%" }} />
            </div>
            <div className="landing-approval-chip">
              <LockKeyhole size={14} aria-hidden="true" />
              approval gate on
            </div>
          </div>
        </div>

        <div className="landing-hero-content landing-reveal is-visible">
          <div className="landing-kicker">
            <RadioTower size={18} aria-hidden="true" />
            GitLab operations intelligence for teams that ship carefully
          </div>
          <h1>Panopticon</h1>
          <p>
            A production-grade agent console that watches GitLab delivery risk, explains failed pipelines, drafts Slack and GitLab actions, and prepares safe code-change plans with evidence and approvals.
          </p>
          <div className="landing-hero-actions">
            <Link href="/signup" className="landing-primary-button landing-primary-large">
              Create workspace
              <ArrowRight size={18} aria-hidden="true" />
            </Link>
            <Link href="/login" className="landing-secondary-button landing-primary-large">
              Open console
              <Play size={17} aria-hidden="true" />
            </Link>
          </div>
        </div>
      </section>

      <section id="workflow" className="landing-section landing-reveal">
        <div className="landing-section-heading">
          <span>Workflow</span>
          <h2>From noisy GitLab signals to reviewed operational action.</h2>
          <p>Panopticon is designed for the actual developer path: connect tools, sync evidence, ask the agent, review recommendations, then approve the exact action you want taken.</p>
        </div>
        <div className="landing-workflow">
          {workflow.map((item, index) => (
            <article key={item.title} className="landing-workflow-step">
              <div className="landing-step-number">{index + 1}</div>
              <item.icon size={22} aria-hidden="true" />
              <h3>{item.title}</h3>
              <p>{item.detail}</p>
            </article>
          ))}
        </div>
      </section>

      <section id="agent" className="landing-section landing-agent-section landing-reveal">
        <div className="landing-section-heading">
          <span>Agent interface</span>
          <h2>Ask it like a teammate, verify it like a release gate.</h2>
          <p>The chat can format answers as tables, checklists, concise summaries, or fix-plan drafts while staying tied to MCP-retrieved evidence.</p>
        </div>

        <div className="landing-agent-layout">
          <div className="landing-agent-prompts" role="tablist" aria-label="Agent examples">
            {signalCards.map((item, index) => (
              <button
                key={item.title}
                type="button"
                role="tab"
                aria-selected={activeSignal === index}
                onClick={() => setActiveSignal(index)}
                className={activeSignal === index ? "is-active" : ""}
              >
                <span>{item.label}</span>
                <strong>{item.title}</strong>
                <small>{item.detail}</small>
              </button>
            ))}
          </div>

          <div className="landing-chat-preview">
            <div className="landing-chat-header">
              <div>
                <span>Panopticon chat</span>
                <strong>{selected.label}</strong>
              </div>
              <span className={`landing-status landing-status-${selected.tone}`}>grounded</span>
            </div>
            <div className="landing-chat-message landing-chat-user">What should I inspect first?</div>
            <div className="landing-chat-message landing-chat-agent">
              <div className="landing-thinking">
                <span />
                <span />
                <span />
              </div>
              {selected.response}
            </div>
            <div className="landing-evidence-row">
              <span>
                <CircleDot size={12} aria-hidden="true" />
                failed job trace
              </span>
              <span>
                <CircleDot size={12} aria-hidden="true" />
                repository context
              </span>
              <span>
                <CircleDot size={12} aria-hidden="true" />
                memory
              </span>
            </div>
          </div>
        </div>
      </section>

      <section id="security" className="landing-section landing-reveal">
        <div className="landing-section-heading">
          <span>Production controls</span>
          <h2>Agentic does not mean uncontrolled.</h2>
          <p>Every automated path is shaped around explicit tools, scoped data, answer validation, and human approval before external writes.</p>
        </div>
        <div className="landing-capability-grid">
          {capabilities.map((item) => (
            <article key={item.title} className="landing-capability">
              <item.icon size={22} aria-hidden="true" />
              <h3>{item.title}</h3>
              <p>{item.detail}</p>
            </article>
          ))}
        </div>
      </section>

      <section className="landing-final-cta landing-reveal">
        <div>
          <span>Ready for a real workspace</span>
          <h2>Connect GitLab, bring Slack, and let Panopticon explain what matters.</h2>
        </div>
        <div className="landing-hero-actions">
          <Link href="/signup" className="landing-primary-button landing-primary-large">
            Start workspace
            <ArrowRight size={18} aria-hidden="true" />
          </Link>
          <Link href="/dashboard" className="landing-secondary-button landing-primary-large">
            View console
            <Activity size={17} aria-hidden="true" />
          </Link>
        </div>
      </section>
    </main>
  );
}
