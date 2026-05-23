import hashlib
import hmac
import time
from urllib.parse import parse_qs

import httpx
from fastapi import HTTPException, Request

from app.config import get_settings


class SlackNotifier:
    def __init__(self, webhook_url: str = "", bot_token: str = "", default_channel: str = "") -> None:
        self.settings = get_settings()
        self.webhook_url = webhook_url or self.settings.slack_webhook_url
        self.bot_token = bot_token or self.settings.slack_bot_token
        self.default_channel = default_channel or self.settings.slack_default_channel

    def send(self, message: str) -> dict:
        return self.send_alert(title="Panopticon alert", message=message, severity="info")

    def send_alert(self, *, title: str, message: str, severity: str, fields: dict | None = None) -> dict:
        payload = self._payload(title=title, message=message, severity=severity, fields=fields or {})
        if self.settings.dry_run_actions:
            return {"status": "dry_run", "payload": payload}
        if self.webhook_url:
            response = httpx.post(self.webhook_url, json=payload, timeout=10)
            response.raise_for_status()
            return {"status": "sent", "code": response.status_code}
        if self.bot_token and self.default_channel:
            response = httpx.post(
                "https://slack.com/api/chat.postMessage",
                headers={"Authorization": f"Bearer {self.bot_token}"},
                json={"channel": self.default_channel, **payload},
                timeout=10,
            )
            response.raise_for_status()
            body = response.json()
            if not body.get("ok"):
                return {"status": "failed", "error": body.get("error", "Slack chat.postMessage failed")}
            return {"status": "sent", "code": response.status_code}
        return {"status": "dry_run", "reason": "Slack is not connected", "payload": payload}

    def _payload(self, *, title: str, message: str, severity: str, fields: dict) -> dict:
        severity_label = severity.upper()
        field_blocks = [
            {
                "type": "mrkdwn",
                "text": f"*{key}:*\n{value}",
            }
            for key, value in fields.items()
            if value
        ]
        blocks = [
            {
                "type": "header",
                "text": {"type": "plain_text", "text": f"Panopticon {severity_label}: {title}"[:150]},
            },
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": message[:2800]},
            },
        ]
        if field_blocks:
            blocks.append({"type": "section", "fields": field_blocks[:8]})
        return {"text": f"Panopticon {severity_label}: {title}", "blocks": blocks}


async def verified_slack_body(request: Request, *, tolerance_seconds: int = 300) -> bytes:
    settings = get_settings()
    body = await request.body()
    if not settings.slack_signing_secret:
        raise HTTPException(status_code=403, detail="Slack signing secret is not configured")

    timestamp = request.headers.get("X-Slack-Request-Timestamp", "")
    signature = request.headers.get("X-Slack-Signature", "")
    if not timestamp or not signature:
        raise HTTPException(status_code=403, detail="Missing Slack signature headers")

    try:
        timestamp_int = int(timestamp)
    except ValueError:
        raise HTTPException(status_code=403, detail="Invalid Slack timestamp") from None

    if abs(int(time.time()) - timestamp_int) > tolerance_seconds:
        raise HTTPException(status_code=403, detail="Stale Slack request")

    base = b"v0:" + timestamp.encode("utf-8") + b":" + body
    expected = "v0=" + hmac.new(settings.slack_signing_secret.encode("utf-8"), base, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, signature):
        raise HTTPException(status_code=403, detail="Invalid Slack signature")
    return body


def parse_slack_form(body: bytes) -> dict[str, str]:
    parsed = parse_qs(body.decode("utf-8"), keep_blank_values=True)
    return {key: values[0] if values else "" for key, values in parsed.items()}
