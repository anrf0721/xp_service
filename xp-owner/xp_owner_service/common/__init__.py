from datetime import datetime, timezone
from uuid import uuid4

FLOW_KEY = "App预约保养步骤"
EXACT_QUESTION = "如何在 App 里预约保养"
COLLECT_MS = 1500
MAX_COLLECT_MS = 8000
LEASE_SECONDS = 30
MAX_ATTEMPTS = 3


def now():
    return datetime.now(timezone.utc)


def new_id():
    return uuid4().hex


class Rejected(Exception):
    def __init__(self, reason, status_code=409):
        self.reason = reason
        self.status_code = status_code
        super().__init__(reason)
