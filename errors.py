from __future__ import annotations


class ApiError(Exception):
    """A deliberate, non-sensitive API error shown to the participant UI."""

    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message

    def as_payload(self) -> dict[str, object]:
        return {
            "ok": False,
            "error": {"code": self.code, "message": self.message},
        }
