from pathlib import Path
import json

from app.config import get_settings


PROMPT_FILES = {
    "deployment_risk": "deployment_risk.md",
    "pipeline_failure_analysis": "pipeline_failure_analysis.md",
    "incident_timeline": "incident_timeline.md",
    "mr_bottleneck": "mr_bottleneck.md",
}


class GeminiReasoner:
    """Boundary for Vertex AI Agent Builder/Gemini reasoning.

    The MVP keeps deterministic local behavior so the application remains demoable
    without cloud credentials. Real Gemini calls should be implemented behind this
    interface.
    """

    def __init__(self) -> None:
        self.settings = get_settings()
        self.prompt_root = Path(__file__).resolve().parents[3] / "prompts"

    def summarize(self, *, task: str, context: dict) -> str:
        prompt = self.load_prompt(task)
        if not self.settings.gemini_enabled:
            return self._local_summary(task=task, prompt=prompt, context=context)
        return self._generate_live(task=task, prompt=prompt, context=context)

    def chat_answer(self, *, question: str, intent: str, subject: str, evidence: list[dict], deterministic_draft: str) -> str:
        """Generate a grounded chat answer with Gemini.

        The chat agent remains evidence-first: retrieval and action proposal happen in
        application code, then Gemini writes the answer using only those records.
        """
        if not self.settings.gemini_enabled:
            return deterministic_draft

        prompt = self._chat_prompt()
        context = {
            "question": question,
            "intent": intent,
            "subject": subject,
            "evidence": evidence,
            "deterministic_draft": deterministic_draft,
        }
        generated = self._generate_live(task="chat_answer", prompt=prompt, context=context, max_output_tokens=2048)
        if _is_live_failure(generated):
            return deterministic_draft
        if _looks_incomplete(generated):
            repaired = self._repair_chat_answer(question=question, subject=subject, evidence=evidence, incomplete_answer=generated)
            if not _is_live_failure(repaired) and not _looks_incomplete(repaired):
                return repaired
            return deterministic_draft
        return generated

    def grounded_recommendation(
        self,
        *,
        issue_type: str,
        project_path: str,
        question: str,
        evidence: list[dict],
        deterministic_draft: str,
    ) -> str:
        if not self.settings.gemini_enabled:
            return deterministic_draft

        prompt = self._grounded_recommendation_prompt()
        generated = self._generate_live(
            task="grounded_recommendation",
            prompt=prompt,
            context={
                "issue_type": issue_type,
                "project_path": project_path,
                "question": question,
                "evidence": evidence,
                "deterministic_draft": deterministic_draft,
            },
            max_output_tokens=1600,
        )
        if _is_live_failure(generated) or _looks_incomplete(generated):
            return deterministic_draft
        return generated

    def load_prompt(self, task: str) -> str:
        filename = PROMPT_FILES.get(task)
        if not filename:
            return "You are Panopticon, an autonomous GitLab operations intelligence agent."
        path = self.prompt_root / filename
        if not path.exists():
            return "You are Panopticon, an autonomous GitLab operations intelligence agent."
        return path.read_text(encoding="utf-8")

    def _local_summary(self, *, task: str, prompt: str, context: dict) -> str:
        project = context.get("project_path") or context.get("project") or "the project"
        evidence_count = len(context.get("evidence", []) or context.get("reasons", []) or [])
        return (
            f"Local reasoning summary for {task}: Panopticon analyzed {project} "
            f"with {evidence_count} evidence signals using prompt '{prompt.splitlines()[0]}'."
        )

    def _generate_live(self, *, task: str, prompt: str, context: dict, max_output_tokens: int = 1200) -> str:
        try:
            from google import genai
            from google.genai import types
        except ImportError as exc:
            return f"Gemini is enabled, but google-genai is not installed: {exc}"

        try:
            client = self._client(genai)
            contents = self._build_contents(task=task, prompt=prompt, context=context)
            response = client.models.generate_content(
                model=self.settings.gemini_model,
                contents=contents,
                config=types.GenerateContentConfig(
                    temperature=0.2,
                    max_output_tokens=max_output_tokens,
                ),
            )
            text = getattr(response, "text", "") or ""
            return text.strip() or "Gemini returned an empty response."
        except Exception as exc:
            return f"Gemini live reasoning failed: {exc}"

    def _client(self, genai_module):
        if self.settings.google_genai_use_vertexai:
            return genai_module.Client(
                vertexai=True,
                project=self.settings.google_cloud_project,
                location=self.settings.google_cloud_location,
            )
        if self.settings.gemini_api_key:
            return genai_module.Client(api_key=self.settings.gemini_api_key)
        return genai_module.Client()

    def _build_contents(self, *, task: str, prompt: str, context: dict) -> str:
        context_json = json.dumps(context, indent=2, sort_keys=True, default=str)
        if task in {"chat_answer", "chat_repair"}:
            return "\n\n".join(
                [
                    prompt,
                    (
                        "Write a complete operational answer in plain text. "
                        "Use the user's requested format when it is clear. "
                        "Markdown tables are allowed only when the user explicitly asks for a table or the deterministic draft is already a table. "
                        "Otherwise use 3 to 6 short complete sentences or compact bullets. "
                        "Do not end with an unfinished phrase, conjunction, or preposition. "
                        "End the final sentence with a period."
                    ),
                    f"Task: {task}",
                    f"Context:\n{context_json}",
                ]
            )
        return "\n\n".join(
            [
                prompt,
                (
                    "Return exactly 3 short plain-text lines with no Markdown formatting: "
                    "1) Risk/diagnosis, 2) Evidence, 3) Next action. "
                    "Finish every sentence completely."
                ),
                f"Task: {task}",
                f"Context:\n{context_json}",
            ]
        )

    def _chat_prompt(self) -> str:
        return "\n".join(
            [
                "You are Panopticon, an agentic GitLab operations assistant.",
                "Answer the developer's question using only the supplied Panopticon evidence.",
                "If the evidence does not prove something, say what is missing and what to inspect next.",
                "Do not invent GitLab, Slack, incident, or pipeline facts.",
                "Be specific, concise, and operational. Prefer concrete next steps over generic advice.",
                "When an action is proposed, remind the user it still needs approval before execution.",
                "Use Markdown tables or checklists only if the user asks for that format.",
            ]
        )

    def _grounded_recommendation_prompt(self) -> str:
        return "\n".join(
            [
                "You are Panopticon's grounded recommendation engine.",
                "Use only the supplied evidence bundle.",
                "Name concrete files, jobs, pipelines, MRs, and commits only when they appear in evidence.",
                "If the evidence is weak, explicitly say the root cause cannot be determined yet.",
                "Return one short paragraph followed by one concrete next step sentence.",
                "Do not use Markdown tables.",
            ]
        )

    def _repair_chat_answer(self, *, question: str, subject: str, evidence: list[dict], incomplete_answer: str) -> str:
        prompt = "\n".join(
            [
                "You are Panopticon, an agentic GitLab operations assistant.",
                "The previous model answer was incomplete.",
                "Rewrite it into a complete answer using only the supplied evidence.",
                "Do not mention that you are repairing an answer.",
            ]
        )
        return self._generate_live(
            task="chat_repair",
            prompt=prompt,
            context={
                "question": question,
                "subject": subject,
                "evidence": evidence,
                "incomplete_answer": incomplete_answer,
            },
            max_output_tokens=2048,
        )


def _is_live_failure(text: str) -> bool:
    lowered = text.lower()
    return (
        not text.strip()
        or "gemini is enabled, but google-genai is not installed" in lowered
        or "gemini live reasoning failed" in lowered
        or "gemini returned an empty response" in lowered
    )


def _looks_incomplete(text: str) -> bool:
    stripped = text.strip()
    if not stripped:
        return True
    lower = stripped.lower().rstrip()
    unfinished_endings = (
        " on",
        " in",
        " at",
        " with",
        " from",
        " to",
        " for",
        " by",
        " of",
        " and",
        " or",
        " because",
        " due to",
        " shows",
        " shows this",
    )
    if lower.endswith(unfinished_endings):
        return True
    return stripped[-1] not in ".!?"


def _chat_failure_message(text: str) -> str:
    if "404" in text and "not_found" in text.lower():
        return (
            "Gemini is configured, but Vertex AI rejected the request because this Google Cloud project does not currently have access to the configured model. "
            "I did not use the deterministic fallback as the assistant answer. Open the configured model in Vertex AI Model Garden for project panopticon-495816, then ask again."
        )
    return (
        "Gemini is configured, but the live model call failed for this request. "
        "I did not use the deterministic fallback as the assistant answer. Check the backend Gemini setup and try again."
    )
