from app.integrations.slack import SlackNotifier


def main() -> None:
    notifier = SlackNotifier()
    mode = "live" if notifier.settings.slack_webhook_url and not notifier.settings.dry_run_actions else "dry-run"
    result = notifier.send_alert(
        title="Slack integration smoke test",
        severity="info",
        message=(
            "This is a Panopticon Slack smoke test. If DRY_RUN_ACTIONS=true, "
            "this is only simulated. If DRY_RUN_ACTIONS=false, this should appear in Slack."
        ),
        fields={
            "Service": "Panopticon",
            "Mode": mode,
        },
    )
    print(result)


if __name__ == "__main__":
    main()
