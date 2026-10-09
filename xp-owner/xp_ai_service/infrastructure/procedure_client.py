"""HTTP reader for the current procedure. Copies text; never calls a model."""

from __future__ import annotations

from dataclasses import dataclass

import httpx


FAILURE_READ = "流程读取失败"


@dataclass(frozen=True, slots=True)
class ProcedureRead:
    available: bool
    flow_key: str | None = None
    version_id: str | None = None
    version_label: str | None = None
    title: str | None = None
    steps: str | None = None
    boundary: str | None = None
    failure_reason: str | None = None


class ProcedureClient:
    def __init__(self, base_url: str, token: str, flow_key: str, timeout_seconds: float = 5.0) -> None:
        self._base_url = base_url.rstrip("/")
        self._token = token
        self._flow_key = flow_key
        self._timeout = timeout_seconds

    def read_current(self) -> ProcedureRead:
        url = f"{self._base_url}/internal/procedures/current"
        headers = {"X-Internal-Service-Token": self._token}
        try:
            response = httpx.get(
                url,
                params={"flow_key": self._flow_key},
                headers=headers,
                timeout=self._timeout,
            )
            response.raise_for_status()
            body = response.json()
        except Exception:
            return ProcedureRead(available=False, failure_reason=FAILURE_READ)
        if not isinstance(body, dict) or body.get("available") is not True:
            return ProcedureRead(available=False)
        try:
            return ProcedureRead(
                available=True,
                flow_key=_verbatim(body.get("flow_key")),
                version_id=_verbatim(body.get("version_id")),
                version_label=_verbatim(body.get("version_label")),
                title=_verbatim(body.get("title")),
                steps=_verbatim(body.get("steps")),
                boundary=_verbatim(body.get("boundary")),
            )
        except TypeError:
            return ProcedureRead(available=False, failure_reason=FAILURE_READ)


def _verbatim(value: object) -> str | None:
    if value is None:
        return None
    if type(value) is not str:
        raise TypeError("procedure text must be a string")
    return value
