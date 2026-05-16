import os

import httpx
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.actions.dispatcher import ActionDispatcher
from app.config import get_settings
from app.database import Base
from app.integrations.gitlab import GitLabClient
from app.integrations.slack import SlackNotifier
from app.models import Recommendation


def _clear_settings_cache():
    get_settings.cache_clear()


def test_gitlab_comment_dry_run(monkeypatch):
    monkeypatch.setenv("DRY_RUN_ACTIONS", "true")
    monkeypatch.setenv("GITLAB_TOKEN", "token")
    _clear_settings_cache()

    result = GitLabClient().create_merge_request_note("demo/project", "7", "hello")

    assert result["status"] == "dry_run"
    assert result["target"] == "demo/project!7"


def test_slack_send_dry_run_without_webhook(monkeypatch):
    monkeypatch.setenv("DRY_RUN_ACTIONS", "true")
    monkeypatch.delenv("SLACK_WEBHOOK_URL", raising=False)
    _clear_settings_cache()

    result = SlackNotifier().send("Pipeline failed")

    assert result["status"] == "dry_run"


def test_slack_send_posts_when_live(monkeypatch):
    sent = {}

    def fake_post(url, json, timeout):
        sent["url"] = url
        sent["json"] = json
        sent["timeout"] = timeout
        return httpx.Response(200, request=httpx.Request("POST", url))

    monkeypatch.setenv("DRY_RUN_ACTIONS", "false")
    monkeypatch.setenv("SLACK_WEBHOOK_URL", "https://hooks.slack.test/services/demo")
    monkeypatch.setattr(httpx, "post", fake_post)
    _clear_settings_cache()

    result = SlackNotifier().send("Incident opened")

    assert result["status"] == "sent"
    assert sent["json"]["text"] == "Panopticon INFO: Panopticon alert"
    assert sent["json"]["blocks"]


def test_dispatcher_marks_recommendation_dry_run(monkeypatch):
    monkeypatch.setenv("DRY_RUN_ACTIONS", "true")
    monkeypatch.setenv("DISPATCH_ACTIONS", "true")
    _clear_settings_cache()

    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    db = Session()
    recommendation = Recommendation(
        project_path="demo/project",
        source_type="risk",
        source_id="1",
        channel="gitlab_comment",
        message="Risk is high",
    )
    db.add(recommendation)
    db.flush()

    result = ActionDispatcher(db).dispatch(recommendation, {"merge_request_iid": "7"})

    assert result["status"] == "dry_run"
    assert recommendation.status == "dry_run"


def teardown_module():
    for key in ["DRY_RUN_ACTIONS", "DISPATCH_ACTIONS", "GITLAB_TOKEN", "SLACK_WEBHOOK_URL"]:
        os.environ.pop(key, None)
    _clear_settings_cache()
