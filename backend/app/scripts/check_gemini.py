from app.agents.gemini import GeminiReasoner


def main() -> None:
    reasoner = GeminiReasoner()
    result = reasoner.summarize(
        task="deployment_risk",
        context={
            "project_path": "demo/checkout-service",
            "reasons": [
                "Checkout service changed.",
                "Infrastructure deployment configuration changed.",
                "No matching test changes were found.",
            ],
            "recommendations": [
                "Require owner review.",
                "Confirm rollback plan.",
            ],
        },
    )
    print(result)


if __name__ == "__main__":
    main()
