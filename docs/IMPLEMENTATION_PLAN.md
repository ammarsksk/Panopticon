# Panopticon Implementation Plan

## Goal

Build an autonomous GitLab operations intelligence agent that keeps software delivery healthy, observable, and unblocked.

## Product Principles

- GitLab is the operational source of truth.
- Deterministic analyzers handle repeatable scoring and extraction.
- Gemini reasoning adds explanation, summarization, and recommendation quality.
- Operational memory is a first-class product feature.
- The dashboard is an engineering console, not a marketing surface.

## Build Phases

1. Scaffold backend, frontend, prompts, workflows, and infrastructure.
2. Implement FastAPI ingestion and operational memory.
3. Normalize GitLab events into internal event records.
4. Add deployment risk, CI failure, MR coordination, and incident intelligence.
5. Add Gemini prompt templates and local fallback behavior.
6. Build the dashboard against backend APIs.
7. Add GitLab and Slack action publishers.
8. Add demo replay data for the hackathon story.
9. Add tests and deployment assets.

## MVP Demo Story

1. A risky merge request is opened.
2. Panopticon creates a risk assessment.
3. A pipeline fails.
4. Panopticon analyzes the log and finds the likely cause.
5. A deployment starts.
6. Production risk increases.
7. A rollback or incident event arrives.
8. Panopticon builds an incident timeline and stores the lesson in memory.

