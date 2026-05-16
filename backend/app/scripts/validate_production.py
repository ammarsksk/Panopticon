from app.config import get_settings


def main() -> None:
    settings = get_settings()
    settings.validate_for_startup()
    print("Production configuration is valid.")


if __name__ == "__main__":
    main()
