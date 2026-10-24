"""A user-explainable failure while fetching or reading a repo."""

from contracts.enums import ErrorCode


class IntakeError(Exception):
    def __init__(self, code: ErrorCode, detail: str, retryable: bool = False) -> None:
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail
        self.retryable = retryable
