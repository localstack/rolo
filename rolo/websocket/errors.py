class WebSocketError(IOError):
    """Base class for websocket errors"""

    pass


class WebSocketDisconnectedError(WebSocketError):
    """Raised when the client has disconnected while the server is still trying to receive data."""

    default_code = 1005
    """https://asgi.readthedocs.io/en/latest/specs/www.html#disconnect-receive-event-ws"""

    def __init__(self, code: int = None):
        self.code = code if code is not None else self.default_code
        super().__init__(f"Websocket disconnected code={self.code}")


class WebSocketProtocolError(WebSocketError):
    """Raised if there is a problem in the interaction between app and the websocket server."""

    pass
