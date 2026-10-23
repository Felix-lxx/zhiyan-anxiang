class CommandRejected(Exception):
    """An expected command rejection mapped to the caller's transport at the edge."""
    def __init__(self, status_code: int, detail: str, headers: dict | None = None):
        super().__init__(detail)
        self.status_code, self.detail, self.headers = status_code, detail, headers
