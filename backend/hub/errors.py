class HubError(Exception):
    """An error whose message is safe to show to API/MCP clients."""

    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message
