"""Adapter API between high-level rolo.websocket.request and an underlying IO frameworks like ASGI or
twisted."""
import dataclasses
import typing as t

from werkzeug.datastructures import Headers

WebSocketEnvironment: t.TypeAlias = t.Dict[str, t.Any]
"""Special WSGIEnvironment that has a ``rolo.websocket`` key that stores a `Websocket` instance."""


class Event:
    """A websocket event (subset of wsproto.events)"""

    pass


@dataclasses.dataclass
class Message(Event):
    data: bytes | str


@dataclasses.dataclass
class TextMessage(Message):
    data: str


@dataclasses.dataclass
class BytesMessage(Message):
    data: bytes


@dataclasses.dataclass
class CreateConnection(Event):
    """
    This indicates the first event of the websocket after a connection upgrade. For example, in wsproto
    this corresponds to a ``Request`` event, or ``websocket.connect`` event in ASGI.
    """

    pass


@dataclasses.dataclass
class AcceptConnection(Event):
    subprotocol: t.Optional[str] = None
    extensions: list[str] = dataclasses.field(default_factory=list)
    extra_headers: list[tuple[bytes, bytes]] = dataclasses.field(default_factory=list)


class WebSocketAdapter:
    """
    Adapter to plug the high-level interfaces ``WebSocket`` and ``WebSocketRequest`` into an IO framework.
    It doesn't cover the full websocket protocol API (for instance there are no Ping/Pong events),
    under the assumption that the lower-level IO framework will abstract them away.
    """

    def receive(
        self,
        timeout: float = None,
    ) -> CreateConnection | Message:
        raise NotImplementedError

    def send(
        self,
        event: Message,
        timeout: float = None,
    ):
        raise NotImplementedError

    def respond(
        self,
        status_code: int,
        headers: Headers = None,
        body: t.Iterable[bytes] = None,
        timeout: float = None,
    ):
        raise NotImplementedError

    def accept(
        self,
        subprotocol: str = None,
        extensions: list[str] = None,
        extra_headers: Headers = None,
        timeout: float = None,
    ):
        raise NotImplementedError

    def close(self, code: int = 1001, reason: str = None, timeout: float = None):
        """
        If the underlying websocket connection has already been closed, this call is ignore, so it's safe
        to always call.
        """
        raise NotImplementedError


class WebSocketListener(t.Protocol):
    """
    Similar protocol to a WSGIApplication, only it expects a Websocket instead of a WSGIEnvironment.
    """

    def __call__(self, environ: WebSocketEnvironment):
        """
        Called when a new Websocket connection is established. To initiate the connection, you need to perform
        the connect handshake yourself. First, receive the ``websocket.connect`` event, and then send the
        ``websocket.accept`` event. Here's a minimal example::

            def accept(self, environ: WebsocketEnvironment):
                websocket: WebSocketAdapter = environ['rolo.websocket']
                event = websocket.receive()
                if isinstance(event, CreateConnection):
                    websocket.accept()
                else:
                    websocket.close(1002)  # protocol error
                    return

                while True:
                    event = websocket.receive()
                    if isinstance(event, CloseConnection):
                            return
                    print(event)

        In reality, you wouldn't be using the websocket adapter directly, the server would probably create a
        ``rolo.websocket.WebSocketRequest`` and serve it accordingly through a ``Gateway``.

        :param environ: The new Websocket environment
        """
        raise NotImplementedError
