class ScannerError(Exception):
    """The scanner timed out, crashed or produced unusable output. kind: timeout | crash."""

    def __init__(self, kind: str, detail: str) -> None:
        super().__init__(f"{kind}: {detail}")
        self.kind = kind
        self.detail = detail
