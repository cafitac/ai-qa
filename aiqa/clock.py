from datetime import UTC, datetime


def default_clock() -> datetime:
    return datetime.now(UTC)
