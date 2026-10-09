"""Internal caller authentication. Empty tokens always fail."""

from __future__ import annotations

from xp_account_service.infrastructure.security import tokens_match


class AuthService:
    def __init__(self, expected_token: str) -> None:
        if expected_token is None or expected_token.strip() == "":
            raise ValueError("internal service token must not be empty")
        self._expected_token = expected_token

    def is_authorized(self, presented_token: str | None) -> bool:
        if presented_token is None or presented_token.strip() == "":
            return False
        return tokens_match(presented_token, self._expected_token)
