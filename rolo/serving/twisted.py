"""
Bindings to serve rolo through Twisted.
"""
import logging
import typing as t
from io import BytesIO
from queue import Empty, Queue

from twisted.internet import reactor
from twisted.internet.protocol import Protocol
from twisted.protocols.policies import ProtocolWrapper
from twisted.python.components import proxyForInterface
from twisted.web.http import HTTPChannel, _GenericHTTPChannelProtocol, urlparse
from twisted.web.http_headers import Headers as TwistedHeaders
from twisted.web.resource import IResource
from twisted.web.server import NOT_DONE_YET, Request, Site
from twisted.web.server import Request as TwistedRequest
from twisted.web.wsgi import WSGIResource, _WSGIResponse, _wsgiString
from werkzeug.datastructures import Headers
from wsproto import ConnectionType, WSConnection, events
from zope.interface import implementer

from rolo.gateway import Gateway
from rolo.gateway.wsgi import WsgiGateway
from rolo.websocket import (
    WebSocketDisconnectedError,
    WebSocketEnvironment,
    WebSocketListener,
    WebSocketProtocolError,
    WebSocketRequest,
)
from rolo.websocket import (
    adapter as rolows,
)

if t.TYPE_CHECKING:
    from _typeshed.wsgi import WSGIEnvironment


LOG = logging.getLogger(__name__)


def to_flat_header_list(headers: TwistedHeaders) -> list[tuple[bytes, bytes]]:
    result = []
    for k, vs in headers.getAllRawHeaders():
        for v in vs:
            result.append((k, v))
    return result


def update_wsgi_environment(environ: "WSGIEnvironment", request: TwistedRequest):
    """
    Update the pre-populated WSGI environment with additional data, needed by rolo, from the webserver
    request object.

    :param environ: the environment to update
    :param request: the webserver request object
    """
    # store raw headers
    environ["rolo.headers"] = to_flat_header_list(request.requestHeaders)

    # TODO: check if twisted input streams are really properly terminated
    # this is needed for streaming requests
    environ["wsgi.input_terminated"] = True

    if not request.path.startswith(b"/"):
        # TODO: this is a bug in Twisted: when the HTTP request contains a full absolute-form URI (when a request is
        #  proxied) instead of a relative path, the `PATH_INFO` is wrong, as Twisted will use the full URI as the path.
        #  `twisted.web.wsgi` will even replace the first char with a slash, leading to something looking like
        #  '/ttp://sns.eu-central-1.amazonaws.com/'
        # See RFC7230: https://tools.ietf.org/html/rfc7230#section-5.3.2
        # > When making a request to a proxy, other than a CONNECT or server-wide OPTIONS request (as detailed below),
        # > a client MUST send the target URI in absolute-form as the request-target.... An example absolute-form
        # > of request-line would be:
        # > GET http://www.example.org/pub/WWW/TheProject.html HTTP/1.1
        #
        # we need to fix it upstream, but this is a global workaround for now
        environ["PATH_INFO"] = urlparse(request.path).path.decode("utf-8")

    # create RAW_URI and REQUEST_URI
    environ["REQUEST_URI"] = request.uri.decode("utf-8")
    environ["RAW_URI"] = request.uri.decode("utf-8")
    # client addr/port
    addr = request.getClientAddress()
    environ["REMOTE_ADDR"] = addr.host
    environ["REMOTE_PORT"] = str(addr.port)


def to_websocket_environment(request: Request) -> WebSocketEnvironment:
    """
    Creates a pseudo WSGI environment to be used for the rolo WebsocketRequest. Partially copied from twisted.web.wsgi.

    :param request: the twisted webserver request
    :return: a WSGI-like environment for rolo
    """
    if request.prepath:
        scriptName = b"/" + b"/".join(request.prepath)
    else:
        scriptName = b""

    if request.postpath:
        pathInfo = b"/" + b"/".join(request.postpath)
    else:
        pathInfo = b""

    parts = request.uri.split(b"?", 1)
    if len(parts) == 1:
        queryString = b""
    else:
        queryString = parts[1]

    environ = {
        "REQUEST_METHOD": "WEBSOCKET",
        "REMOTE_ADDR": _wsgiString(request.getClientAddress().host),
        "REMOTE_PORT": _wsgiString(str(request.getClientAddress().port)),
        "SCRIPT_NAME": _wsgiString(scriptName),
        "PATH_INFO": _wsgiString(pathInfo),
        "QUERY_STRING": _wsgiString(queryString),
        "CONTENT_TYPE": _wsgiString(request.getHeader(b"content-type") or ""),
        "CONTENT_LENGTH": _wsgiString(request.getHeader(b"content-length") or ""),
        "SERVER_NAME": _wsgiString(request.getRequestHostname()),
        "SERVER_PORT": _wsgiString(str(request.getHost().port)),
        "SERVER_PROTOCOL": _wsgiString(request.clientproto),
        "REQUEST_URI": request.uri.decode("utf-8"),
        "RAW_URI": request.uri.decode("utf-8"),
    }

    # store raw headers for rolo
    environ["rolo.headers"] = to_flat_header_list(request.requestHeaders)

    # WSGI headers
    for name, values in request.requestHeaders.getAllRawHeaders():
        name = "HTTP_" + _wsgiString(name).upper().replace("-", "_")
        environ[name] = ",".join(_wsgiString(v) for v in values).replace("\n", " ")

    environ.update(
        {
            "wsgi.version": (1, 0),
            "wsgi.url_scheme": request.isSecure() and "https" or "http",
            "wsgi.run_once": False,
            "wsgi.multithread": True,
            "wsgi.multiprocess": False,
            "wsgi.errors": BytesIO(),
            "wsgi.input": BytesIO(),
        }
    )

    return environ


class TwistedRequestAdapter(TwistedRequest):
    """
    Custom twisted server Request object to handle header casing.
    """

    rawHeaderList: list[tuple[bytes, bytes]]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # instantiate case mappings, these are used by `getAllRawHeaders` to restore casing
        # by default, they are class attributes, so we would override them globally
        self.requestHeaders._caseMappings = dict(self.requestHeaders._caseMappings)
        self.responseHeaders._caseMappings = dict(self.responseHeaders._caseMappings)


class HeaderPreservingHTTPChannel(HTTPChannel):
    """
    Special HTTPChannel implementation that uses ``Headers._caseMappings`` to retain header casing both for
    request headers (server -> WSGI), and  response headers (WSGI -> client).
    """

    requestFactory = TwistedRequestAdapter

    @staticmethod
    def protocol_factory():
        return _GenericHTTPChannelProtocol(HeaderPreservingHTTPChannel())

    def headerReceived(self, line):
        if not super().headerReceived(line):
            return False
        # remember casing of headers for requests
        header, data = line.split(b":", 1)
        request: TwistedRequestAdapter = self.requests[-1]
        request.requestHeaders._caseMappings[header.lower()] = header
        return True

    def writeHeaders(self, version, code, reason, headers):
        """Alternative implementation that writes the raw headers instead of sanitized versions."""
        responseLine = version + b" " + code + b" " + reason + b"\r\n"
        headerSequence = [responseLine]

        for name, value in headers:
            line = name + b": " + value + b"\r\n"
            headerSequence.append(line)

        headerSequence.append(b"\r\n")
        self.transport.writeSequence(headerSequence)

    def isSecure(self):
        # used to determine the WSGI url scheme (http vs https)
        try:
            # ``self.transport`` will be a ``TLSMultiplexer`` instance in our case
            return self.transport.isSecure()
        except AttributeError:
            return super().isSecure()


class HeaderPreservingWSGIResponse(_WSGIResponse):
    def __init__(self, reactor, threadpool, application, request):
        super().__init__(reactor, threadpool, application, request)
        update_wsgi_environment(self.environ, request)

    def startResponse(self, *args, **kwargs):
        result = super().startResponse(*args, **kwargs)
        # before starting the WSGI response, make sure we store the raw case mappings into the response
        # headers
        for header, _ in self.headers:
            header = header.encode("latin-1")
            self.request.responseHeaders._caseMappings[header.lower()] = header
        return result


class HeaderPreservingWSGIResource(WSGIResource):
    def render(self, request):
        response = HeaderPreservingWSGIResponse(
            self._reactor, self._threadpool, self._application, request
        )
        response.start()
        return NOT_DONE_YET


@implementer(IResource)
class WebsocketResourceDecorator(proxyForInterface(IResource)):
    """
    Wrapper around a ``WSGIResource`` that intercepts websocket requests, and calls the
    ``WebSocketListener`` in a separate thread, similar to how ``WSGIResource`` dispatches its requests.
    """

    original: WSGIResource
    isLeaf = True

    def __init__(
        self,
        original: WSGIResource,
        websocketListener: WebSocketListener,
    ):
        super().__init__(original)
        self.websocketListener = websocketListener

    def render(self, request: Request):
        if upgrade := request.getHeader("upgrade"):
            if upgrade.lower() == "websocket":
                self._processWebsocket(request)
                return NOT_DONE_YET

        return super().render(request)

    def _processWebsocket(self, request: Request):
        channel = WebSocketChannel(request)
        if isinstance(request.channel.transport, ProtocolWrapper):
            request.transport.wrappedProtocol = channel
        else:
            request.transport.protocol = channel

        channel.initiateUpgrade()

        environment = to_websocket_environment(request)
        environment["rolo.websocket"] = TwistedWebSocketAdapter(channel)
        # WSGIResource also dispatches requests through the threadpool
        self.original._threadpool.callInThread(self.websocketListener, environment)


class WebSocketChannel(Protocol):
    """
    Websocket protocol implementation over twisted. Note this is a ``twisted.internet.Protocol``, not a
    Python Protocol class.
    """

    eventQueue: Queue[events.Event]

    def __init__(self, request: Request):
        self.request = request
        self.wsproto = WSConnection(ConnectionType.SERVER)
        self.eventQueue = Queue()

    @property
    def closed(self):
        return self.request.finished

    def initiateUpgrade(self):
        headers = [(k, v) for k, vs in self.request.requestHeaders.getAllRawHeaders() for v in vs]
        self.wsproto.initiate_upgrade_connection(headers, self.request.path)

        for event in self.wsproto.events():
            self.eventQueue.put(event)
            if isinstance(event, events.CloseConnection):
                self.close()

    def connectionLost(self, reason):
        self.close()

    def dataReceived(self, data: bytes) -> None:
        self.wsproto.receive_data(data)
        for event in self.wsproto.events():
            if isinstance(event, events.Ping):
                self.wsSend(events.Pong(event.payload))
                continue
            # TODO: filter other event types that are not expected by WebSocketAdapter
            if isinstance(event, events.CloseConnection):
                self.close()
            self.eventQueue.put_nowait(event)

    def wsSend(self, event: events.Event):
        request = self.request
        if request.finished:
            return
        data = self.wsproto.send(event)
        request.transport.write(data)

    def wsReject(
        self,
        statusCode: int,
        extraHeaders: Headers,
        body: t.Iterator[bytes] | None = None,
    ):
        # this sends an HTTP response back to the client before the request was upgraded. we could also use
        # ``self.wsSend(events.RejectConnection(statusCode, ...))`` which would write the HTTP response
        # generated by wsproto to the transport, but instead we re-use twisted's request/response mechanism
        # which is cleaner here, though perhaps inconsistent with the rest of the implementation.
        # TODO: set default twisted headers
        request = self.request

        request.setResponseCode(statusCode)
        for k, v in extraHeaders.to_wsgi_list():
            request.responseHeaders.addRawHeader(k, v)

        if body:
            for b in body:
                request.write(b)

        self.close()

    def wsClose(self, code: int = 1000, reason: t.Optional[str] = None):
        try:
            self.wsSend(events.CloseConnection(code, reason))
        finally:
            self.close()

    def close(self):
        if not self.request.finished:
            self.request.finish()
            # special internal poison pill
            self.eventQueue.put_nowait(events.CloseConnection(None))


class TwistedWebSocketAdapter(rolows.WebSocketAdapter):
    channel: WebSocketChannel

    def __init__(self, channel: WebSocketChannel):
        self.channel = channel

    def receive(self, timeout: float = None) -> rolows.CreateConnection | rolows.Message:
        try:
            event = self.channel.eventQueue.get(timeout=timeout)
        except Empty as e:
            raise TimeoutError(
                f"Timeout error while reading events from websocket after {timeout}s"
            ) from e

        if isinstance(event, events.Request):
            return rolows.CreateConnection()
        if isinstance(event, events.BytesMessage):
            return rolows.BytesMessage(event.data)
        elif isinstance(event, events.TextMessage):
            return rolows.TextMessage(event.data)
        elif isinstance(event, events.CloseConnection):
            raise WebSocketDisconnectedError(event.code)
        else:
            raise WebSocketProtocolError(f"Unexpected event type {event.__class__.__name__}")

    def send(self, event: rolows.Message, timeout: float = None):
        if isinstance(event, rolows.TextMessage):
            self.channel.wsSend(events.TextMessage(event.data))
        elif isinstance(event, rolows.BytesMessage):
            self.channel.wsSend(events.BytesMessage(event.data))
        else:
            raise TypeError(f"Unexpected event type {event.__class__.__name__}")

    def reject(
        self,
        status_code: int,
        headers: Headers = None,
        body: t.Iterable[bytes] = None,
        timeout: float = None,
    ):
        self.channel.wsReject(status_code, headers, body)

    def accept(
        self,
        subprotocol: str = None,
        extensions: list[str] = None,
        extra_headers: Headers = None,
        timeout: float = None,
    ):
        if extra_headers:
            raw_headers = [
                (k.encode("latin-1"), v.encode("latin-1")) for k, v in extra_headers.to_wsgi_list()
            ]
        else:
            raw_headers = []

        # TODO: extensions
        event = events.AcceptConnection(subprotocol, extensions=[], extra_headers=raw_headers)
        self.channel.wsSend(event)

    def close(self, code: int = 1001, reason: str = None, timeout: float = None):
        if not self.channel.closed:
            self.channel.wsClose(code, reason)


class GatewayResource(proxyForInterface(IResource)):
    """
    Compound ``Resource`` implementation to serve a Gateway through a ``Site``.
    """

    def __init__(self, gateway: Gateway, reactor, threadpool):
        self.gateway = gateway
        super().__init__(
            WebsocketResourceDecorator(
                original=HeaderPreservingWSGIResource(reactor, threadpool, WsgiGateway(gateway)),
                websocketListener=WebSocketRequest.listener(gateway.accept),
            )
        )


class TwistedGateway(Site):
    """
    Expose a Gateway as a ``twisted.web.server.Site`` which is a ProtocolFactory that can be served via
    ``reactor.listenTCP``.
    """

    def __init__(self, gateway: Gateway):
        super().__init__(
            GatewayResource(gateway, reactor, reactor.getThreadPool()), TwistedRequestAdapter
        )
        self.protocol = HeaderPreservingHTTPChannel.protocol_factory
