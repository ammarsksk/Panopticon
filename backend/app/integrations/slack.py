import httpx

from app.config import get_settings


class SlackNotifier:
    def __init__(self) -> None:
        self.settings = get_settings()

    def send(self, message: str) -> dict:
        return self.send_alert(title="Panopticon alert", message=message, severity="info")

    def send_alert(self, *, title: str, message: str, severity: str, fields: dict | None = None) -> dict:
        payload = self._payload(title=title, message=message, severity=severity, fields=fields or {})
        if self.settings.dry_run_actions or not self.settings.slack_webhook_url:
            return {"status": "dry_run", "payload": payload}
        response = httpx.post(self.settings.slack_webhook_url, json=payload, timeout=10)
        response.raise_for_status()
        return {"status": "sent", "code": response.status_code}

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
