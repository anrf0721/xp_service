from datetime import datetime, timedelta, timezone


class Clock:
    def __init__(self, start: datetime | None = None):
        self.value = start or datetime(2026, 7, 14, 8, 0, tzinfo=timezone.utc)

    def now(self) -> datetime:
        return self.value

    def advance(self, milliseconds: int) -> datetime:
        self.value = self.value + timedelta(milliseconds=milliseconds)
        return self.value
