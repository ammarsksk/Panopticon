import json
import argparse
from pathlib import Path

from app.database import SessionLocal, init_db
from app.event_handlers.gitlab import process_gitlab_event
from app import models


ROOT = Path(__file__).resolve().parents[3]
PAYLOAD_DIR = ROOT / "workflows" / "demo_payloads"


def reset_demo_data(db) -> None:
    for model in (
        models.ActionDispatch,
        models.Recommendation,
        models.MemoryRecord,
        models.IncidentRecord,
        models.MergeRequestSignal,
        models.PipelineInsight,
        models.RiskAssessment,
        models.WebhookReceipt,
        models.OperationalEvent,
    ):
        db.query(model).delete()
    db.commit()


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed Panopticon demo GitLab events.")
    parser.add_argument("--reset", action="store_true", help="Clear existing local demo data before replaying payloads.")
    args = parser.parse_args()

    init_db()
    db = SessionLocal()
    try:
        if args.reset:
            reset_demo_data(db)
        for path in sorted(PAYLOAD_DIR.glob("*.json")):
            payload = json.loads(path.read_text(encoding="utf-8"))
            result = process_gitlab_event(payload, db)
            print(f"seeded {path.name}: {result}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
