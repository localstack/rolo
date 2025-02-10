import functools
import typing as t

from werkzeug import Response
from werkzeug._internal import _wsgi_decoding_dance
from werkzeug.datastructures import EnvironHeaders, Headers, MultiDict
from werkzeug.sansio.request import Request as _SansIORequest
from werkzeug.wsgi import _get_server

from .adapter import (
    BytesMessage,
    CreateConnection,
    Message,
    TextMessage,
    WebSocketAdapter,
    WebSocketEnvironment,
    WebSocketListener,
)
from .errors import WebSocketDisconnectedError, WebSocketProtocolError


class WebSocket:
    """
    High-level interface to interact with a websocket after a handshake has been completed with
    `WebsocketRequest.accept()`.
    """

    request: "WebSocketRequest"
    socket: WebSocketAdapter

    def __init__(self, request: "WebSocketRequest", socket: WebSocketAdapter):
        self.request = request
        self.socket = socket

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    def __iter__(self):
        while True:
            try:
                yield self.receive()
            except WebSocketDisconnectedError:
                break

    def send(self, text_or_bytes: str | bytes, timeout: float = None):
        """
        Send data to the websocket connection.

        :param text_or_bytes: the data to send. Use strings for text-mode sockets (default).
        :param timeout: the timeout in seconds to wait before raising a timeout error
        """
        if text_or_bytes is None:
            raise ValueError("text_or_bytes cannot be None")

        if isinstance(text_or_bytes, str):
            event = TextMessage(text_or_bytes)
        elif isinstance(text_or_bytes, bytes):
            event = BytesMessage(text_or_bytes)
        else:
            raise WebSocketProtocolError(
                f"Cannot send data type {type(text_or_bytes)} over websocket"
            )
        self.socket.send(event, timeout)

    def receive(self) -> str | bytes:
        """
        Receive the next data package from the websocket. Will be string or byte data and set the
        underlying binary for the frame automatically.

        :raise WebSocketDisconnectedError: if the websocket was closed in the meantime
        :raise WebSocketProtocolError: error in the interaction between the app and the webserver
        :return: the next data package from the websocket
        """
        event = self.socket.receive()
        if isinstance(event, Message):
            data = event.data
            if data is None:
                raise WebSocketProtocolError("No data returned by the websocket.")
            return data
        else:
            raise WebSocketProtocolError(
                f"Unexpected websocket event type {event.__class__.__name__}."
            )

    def close(self, code: int = 1000, reason: t.Optional[str] = None, timeout: float = None):
        """
        Closes the websocket connection with specific code.

        :param code: the websocket close code.
        :param reason: optional reason
        :param timeout: connection timeout
        """
        self.socket.close(code, reason, timeout)


class WebSocketRequest(_SansIORequest):
    """
    A websocket request represents the incoming HTTP request to upgrade the connection to a WebSocket
    connection. The request method is an artificial ``WEBSOCKET`` method that can also be used in the Router:
    ``@route("/path", method=["WEBSOCKET"])``.

    The websocket connection needs to be either accepted or rejected. When calling
    ``WebSocketRequest.accept``, an upgrade response will be sent to the client, and the protocol will be
    switched to the bidirectional WebSocket protocol. If ``WebSocketRequest.reject`` is called, the server
    immediately returns an HTTP response and closes the connection.
    """

    def __init__(self, environ: WebSocketEnvironment):
        """
        Creates a new request from the given WebSocketEnvironment. This is like a sans-IO WSGI Environment,
        with an additional field ``rolo.websocket`` that contains a ``WebSocketAdapter`` interface.

        :param environ: the WebSocketEnvironment
        """
        raw_headers = environ.get("rolo.headers")
        if raw_headers:
            # restores raw headers from the server scope, to have proper casing or dashes. This can depend on server
            # behavior, but we want a unified way to keep header casing/formatting.
            # This is similar to what we do in wsgi.py
            headers = Headers(
                MultiDict([(k.decode("latin-1"), v.decode("latin-1")) for (k, v) in raw_headers])
            )
        else:
            headers = Headers(EnvironHeaders(environ))

        # copied from werkzeug.wrappers.request
        super().__init__(
            method=environ.get("REQUEST_METHOD", "WEBSOCKET"),
            scheme=environ.get("wsgi.url_scheme", "ws"),
            server=_get_server(environ),
            root_path=_wsgi_decoding_dance(environ.get("SCRIPT_NAME") or ""),
            path=_wsgi_decoding_dance(environ.get("PATH_INFO") or ""),
            query_string=environ.get("QUERY_STRING", "").encode("latin1"),
            headers=headers,
            remote_addr=environ.get("REMOTE_ADDR"),
        )
        self.environ = environ

        self.shallow = True  # compatibility with werkzeug.Request

        self._upgraded = False
        self._rejected = False

    @property
    def socket(self) -> WebSocketAdapter:
        """
        Returns the underlying WebSocketAdapter from the environment. This is analogous to ``Request.stream``
        in the default werkzeug HTTP request object.

        :return: the WebSocketAdapter from the environment
        """
        return self.environ.get("rolo.websocket") or self.environ.get("asgi.websocket")

    def is_upgraded(self) -> bool:
        """Returns true if ``accept`` was called."""
        return self._upgraded

    def is_rejected(self) -> bool:
        """Returns true if ``reject`` was called."""
        return self._rejected

    def reject(self, response: Response):
        """
        Reject the websocket upgrade and return the given response. Will raise a ``ValueError`` if the
        request has already been accepted or rejected before.

        :param response: the HTTP response to return to the client.
        """
        if self._upgraded:
            raise ValueError("Websocket connection already upgraded")
        if self._rejected:
            raise ValueError("Websocket connection already rejected")

        self.socket.reject(
            response.status_code,
            response.headers,
            response.iter_encoded(),
        )
        self._rejected = True

    def accept(
        self, subprotocol: str = None, headers: Headers = None, timeout: float = None
    ) -> WebSocket:
        """
        Performs the websocket connection upgrade handshake. After calling ``accept``, a new ``Websocket``
        instance is returned that represents the bidirectional communication channel, which you should
        continue operating on. Example::

            def app(request: WebsocketRequest):
                # example: do authorization first
                auth = request.headers.get("Authorization")
                if not is_authorized(auth):
                    request.reject(Response("no dice", 403))
                    return

                # then continue working with the websocket
                with request.accept() as websocket:
                    websocket.send("hello world!")
                    data = websocket.receive()
                    # ...

        The handshake using the WebSocketAdapter works as follows: receive the ``CreateConnection`` event
        from the websocket and then call the ``socket.accept(...)``. If the handshake failed because
        the websocket sent an unexpected exception, the connection is closed and the method raises an error.

        :param subprotocol: The subprotocol the server wishes to accept. Optional
        :param headers: Response headers
        :param timeout: connection timeout
        :return: a websocket
        :raises ProtocolError: if unexpected events were received from the websocket server
        """
        if self._upgraded:
            raise ValueError("Websocket connection already upgraded")
        if self._rejected:
            raise ValueError("Websocket connection already rejected")

        event = self.socket.receive(timeout)
        if isinstance(event, CreateConnection):
            self.socket.accept(subprotocol, [], headers, timeout)
            self._upgraded = True
            return WebSocket(self, self.socket)
        else:
            reason = f"Unexpected event {event.__class__.__name__}"
            self.socket.close(1003, reason)
            raise WebSocketProtocolError(reason)

    def close(self):
        """
        Explicitly close the websocket. If this is called after ``reject(...)`` or ``accept(...)`` has been
        called, this will have no effect. Calling ``reject`` inherently closes the websocket connection
        since it immediately returns an HTTP response. After calling ``accept`` you should call
        ``WebSocket.close`` instead.
        """
        if self._rejected or self._upgraded:
            return
        self.socket.close(1000)

    @classmethod
    def listener(cls, fn: t.Callable[["WebSocketRequest"], None]) -> WebSocketListener:
        """
        Convenience function inspired by ``werkzeug.Request.application`` that transforms a function into a
        ``WebsocketListener`` for the use in server code that support ``WebsocketListeners``. Example::

            @WebsocketRequest.listener
            def app(request: WebSocketRequest):
                with request.accept() as ws:
                    ws.send("hello world")

            adapter = ASGIAdapter(wsgi_app=..., websocket_listener=app)
            # ... serve adapter


        :param fn: the function to wrap
        :return: a WebsocketListener compatible interface
        """
        from werkzeug.exceptions import HTTPException

        @functools.wraps(fn)
        def application(*args):
            request = cls(args[-1])
            try:
                fn(*args[:-1] + (request,))
            except HTTPException as e:
                resp = e.get_response(args[-1])
                request.reject(resp)
            finally:
                request.close()

        return application
