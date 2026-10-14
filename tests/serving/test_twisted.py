import datetime
import http.client
import io
import json
import socket
import ssl as stdlib_ssl
import struct
import threading
import time

import h2.config
import h2.connection
import h2.events
import pytest
import requests
import websocket
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID
from twisted.internet import ssl
from twisted.internet.address import IPv4Address
from twisted.internet.error import ConnectionDone
from twisted.internet.task import Clock
from twisted.internet.testing import StringTransport
from twisted.protocols.tls import TLSMemoryBIOFactory
from twisted.python.failure import Failure
from twisted.web._http2 import H2Connection
from twisted.web.http_headers import Headers as TwistedHeaders
from twisted.web.server import Site
from wsproto import ConnectionType, WSConnection, events
from wsproto.connection import ConnectionState

from rolo import Request, Router, route
from rolo.dispatcher import handler_dispatcher
from rolo.gateway import Gateway
from rolo.gateway.handlers import RouterHandler
from rolo.serving.twisted import (
    H2_PREFACE,
    HeaderPreservingHTTPChannel,
    HeaderPreservingWSGIResource,
    PriorKnowledgeHTTPChannelProtocol,
    TwistedGateway,
    TwistedRequestAdapter,
    TwistedWebSocketAdapter,
    WebSocketChannel,
    WebsocketResourceDecorator,
)
from rolo.testing.pytest import _ServerInfo, get_random_tcp_port, wait_server_is_up
from rolo.websocket import WebSocketListener, WebSocketRequest
from rolo.websocket.adapter import CreateConnection, TextMessage
from rolo.websocket.request import WebSocketDisconnectedError


def test_large_file_upload(serve_twisted_gateway):
    router = Router(handler_dispatcher())

    @route("/hello", methods=["POST"])
    def hello(request: Request):
        return "ok"

    router.add(hello)

    gateway = Gateway(request_handlers=[RouterHandler(router, True)])
    server = serve_twisted_gateway(gateway)

    response = requests.post(server.url + "/hello", io.BytesIO(b"0" * 100001))

    assert response.status_code == 200


def test_full_absolute_form_uri(serve_twisted_gateway):
    router = Router(handler_dispatcher())

    @route("/hello", methods=["GET"])
    def hello(request: Request):
        return {"path": request.path, "raw_uri": request.environ["RAW_URI"]}

    router.add(hello)

    gateway = Gateway(request_handlers=[RouterHandler(router, True)])
    server = serve_twisted_gateway(gateway)
    host = server.url

    conn = http.client.HTTPConnection(host="127.0.0.1", port=server.port)

    # This is what is sent:
    # send: b'GET http://localhost:<port>/hello HTTP/1.1\r\nHost: localhost:<port>\r\nAccept-Encoding: identity\r\n\r\n'
    # note the full URI in the HTTP request
    conn.request("GET", url=f"{host}/hello")
    response = conn.getresponse()

    assert response.status == 200
    response_data = json.loads(response.read())
    assert response_data["path"] == "/hello"
    assert response_data["raw_uri"].startswith("http")


class _FakeTransport:
    def __init__(self):
        self.written = []

    def write(self, data: bytes):
        self.written.append(data)

    def loseConnection(self):
        pass


class _UnfinishedRequest:
    """A twisted request stand-in whose ``finish()`` does not mark it finished, which freezes the channel in
    the window where the closing handshake is complete, but the reactor has not finished the request yet.
    """

    def __init__(self, headers: list[tuple[bytes, bytes]]):
        self.requestHeaders = TwistedHeaders()
        for k, v in headers:
            self.requestHeaders.addRawHeader(k, v)
        self.path = b"/"
        self.transport = _FakeTransport()
        # the channel is only used to lose the connection, which the fake transport does as well
        self.channel = self.transport
        self.finished = False
        self.startedWriting = 0

    def finish(self):
        pass


def _accepted_websocket() -> tuple[TwistedWebSocketAdapter, WSConnection, _FakeTransport]:
    client = WSConnection(ConnectionType.CLIENT)
    request_head = client.send(events.Request(host="localhost", target="/")).split(b"\r\n\r\n")[0]
    headers = [
        tuple(part.strip() for part in line.split(b":", 1))
        for line in request_head.split(b"\r\n")[1:]
    ]
    request = _UnfinishedRequest(headers)
    channel = WebSocketChannel(request)
    channel.initiateUpgrade()
    adapter = TwistedWebSocketAdapter(channel)
    assert isinstance(adapter.receive(timeout=1), CreateConnection)
    adapter.accept()

    client.receive_data(b"".join(request.transport.written))
    assert isinstance(next(client.events()), events.AcceptConnection)
    request.transport.written.clear()
    return adapter, client, request.transport


def test_websocket_close_after_client_close_before_request_finished():
    adapter, client, transport = _accepted_websocket()

    adapter.channel.dataReceived(client.send(events.CloseConnection(4001, "bye")))
    assert adapter.channel.wsproto.state == ConnectionState.CLOSED
    assert not adapter.channel.closed
    echoed = b"".join(transport.written)
    client.receive_data(echoed)
    assert next(client.events()) == events.CloseConnection(4001, "bye")

    with pytest.raises(WebSocketDisconnectedError) as e:
        adapter.receive(timeout=1)
    assert (e.value.code, e.value.reason) == (4001, "bye")

    adapter.close(1000)
    adapter.close(1000)

    assert b"".join(transport.written) == echoed


def test_websocket_close_twice_before_request_finished():
    adapter, client, transport = _accepted_websocket()

    adapter.close(1000)
    assert adapter.channel.wsproto.state == ConnectionState.LOCAL_CLOSING
    sent = b"".join(transport.written)

    adapter.close(1000)
    adapter.send(TextMessage("too late"))

    assert b"".join(transport.written) == sent


@pytest.fixture(scope="module")
def self_signed_cert() -> tuple[bytes, bytes]:
    """A self-signed certificate and private key for ``localhost``, both PEM encoded."""
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "localhost")])
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(days=1))
        .not_valid_after(now + datetime.timedelta(days=1))
        .add_extension(x509.SubjectAlternativeName([x509.DNSName("localhost")]), critical=False)
        .sign(key, hashes.SHA256())
    )
    key_pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    return cert.public_bytes(serialization.Encoding.PEM), key_pem


@pytest.fixture
def serve_twisted_tls_server(twisted_reactor, self_signed_cert):
    """Like ``serve_twisted_tcp_server``, but serves the protocol factory over TLS. The server accepts ``h2`` and
    ``http/1.1`` via ALPN."""
    ports = []

    def _create(protocol_factory, scheme: str = "https"):
        cert_pem, key_pem = self_signed_cert
        certificate = ssl.PrivateCertificate.loadPEM(cert_pem + key_pem)
        options = ssl.CertificateOptions(
            privateKey=certificate.privateKey.original,
            certificate=certificate.original,
            acceptableProtocols=[b"h2", b"http/1.1"],
        )
        factory = TLSMemoryBIOFactory(options, False, protocol_factory)

        port = get_random_tcp_port()
        ports.append(twisted_reactor.listenTCP(port, factory))
        srv = _ServerInfo("localhost", port, f"{scheme}://localhost:{port}")
        assert wait_server_is_up(srv), f"gave up waiting for {srv}"
        return srv

    yield _create

    for _port in ports:
        _port.stopListening()


@pytest.fixture
def serve_twisted_tls_websocket_listener(twisted_reactor, serve_twisted_tls_server):
    """Like ``serve_twisted_websocket_listener``, but serves the listener over TLS."""

    def _create(websocket_listener: WebSocketListener):
        site = Site(
            WebsocketResourceDecorator(
                original=HeaderPreservingWSGIResource(
                    twisted_reactor, twisted_reactor.getThreadPool(), None
                ),
                websocketListener=websocket_listener,
            ),
            requestFactory=TwistedRequestAdapter,
        )
        site.protocol = HeaderPreservingHTTPChannel.protocol_factory
        return serve_twisted_tls_server(site, scheme="wss")

    yield _create


def test_websocket_tls_send_and_close_from_listener_thread(serve_twisted_tls_websocket_listener):
    """The listener runs in a threadpool thread, but twisted transports, and the TLS connection state
    in particular, may only be touched from the reactor thread. Writing to them directly from the
    listener thread races with the reactor processing the client's TLS records, which breaks the
    connection before the client reads the upgrade response."""

    @WebSocketRequest.listener
    def app(request: WebSocketRequest):
        with request.accept() as ws:
            ws.send("hello")

    server = serve_twisted_tls_websocket_listener(app)

    for _ in range(200):
        client = websocket.WebSocket(sslopt={"cert_reqs": stdlib_ssl.CERT_NONE})
        client.connect(server.url, timeout=5)
        assert client.recv() == "hello"
        client.close()


def test_websocket_tls_close_handshake_client_initiated(serve_twisted_tls_websocket_listener):
    """After the closing handshake, the server terminates the connection over TLS too. The HTTP channel is
    registered as producer of the TLS transport, which defers its shutdown until no producer is registered,
    so terminating the TLS transport directly never closes the connection."""
    disconnected = threading.Event()

    @WebSocketRequest.listener
    def app(request: WebSocketRequest):
        with request.accept() as ws:
            with pytest.raises(WebSocketDisconnectedError):
                ws.receive()
        disconnected.set()

    server = serve_twisted_tls_websocket_listener(app)

    client = websocket.WebSocket(sslopt={"cert_reqs": stdlib_ssl.CERT_NONE})
    client.connect(server.url, timeout=5)
    client.send_close(websocket.STATUS_NORMAL)

    frame = client.recv_frame()
    assert frame.opcode == websocket.ABNF.OPCODE_CLOSE
    assert struct.unpack("!H", frame.data[:2])[0] == websocket.STATUS_NORMAL

    client.sock.settimeout(5)
    assert client.sock.recv(1) == b"", "expected the server to terminate the TLS connection"
    assert disconnected.wait(timeout=3)


@pytest.fixture
def protocol_gateway() -> Gateway:
    """A gateway that responds to ``/protocol`` with the HTTP protocol version the request was served with."""
    router = Router(handler_dispatcher())

    @route("/protocol")
    def protocol(request: Request):
        return {"protocol": request.environ["SERVER_PROTOCOL"]}

    router.add(protocol)
    return Gateway(request_handlers=[RouterHandler(router, True)])


def _h2_get(
    sock: socket.socket, scheme: str, path: str, fragment: bool = False
) -> tuple[int, bytes]:
    """Sends a GET request over ``sock`` with the HTTP/2 client of ``h2`` and returns the status code and body.
    With ``fragment``, the connection preface is sent in small pieces that arrive in separate reads.
    """
    conn = h2.connection.H2Connection(h2.config.H2Configuration(client_side=True))
    conn.initiate_connection()
    conn.send_headers(
        1,
        [(":method", "GET"), (":path", path), (":scheme", scheme), (":authority", "localhost")],
        end_stream=True,
    )
    data = conn.data_to_send()

    if fragment:
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        for i in range(0, len(H2_PREFACE), 5):
            sock.sendall(data[i : min(i + 5, len(H2_PREFACE))])
            time.sleep(0.01)
        sock.sendall(data[len(H2_PREFACE) :])
    else:
        sock.sendall(data)

    status, body = None, b""
    first = True
    while True:
        received = sock.recv(65535)
        assert received, "server closed the connection"
        if first:
            assert not received.startswith(b"HTTP/"), f"server responded with HTTP/1: {received!r}"
            first = False

        for event in conn.receive_data(received):
            if isinstance(event, h2.events.ResponseReceived):
                status = int(dict(event.headers)[b":status"])
            elif isinstance(event, h2.events.DataReceived):
                body += event.data
                conn.acknowledge_received_data(event.flow_controlled_length, event.stream_id)
            elif isinstance(event, h2.events.StreamEnded):
                return status, body
        sock.sendall(conn.data_to_send())


def test_http1_over_tls(serve_twisted_tls_server, protocol_gateway):
    server = serve_twisted_tls_server(TwistedGateway(protocol_gateway))

    response = requests.get(server.url + "/protocol", verify=False)

    assert response.status_code == 200
    assert response.json() == {"protocol": "HTTP/1.1"}


@pytest.mark.parametrize("fragment", [False, True], ids=["whole", "fragmented"])
@pytest.mark.parametrize("alpn", [True, False], ids=["alpn", "no-alpn"])
def test_http2_over_tls(serve_twisted_tls_server, protocol_gateway, alpn, fragment):
    """Without ALPN, the client starts sending HTTP/2 right after the TLS handshake. The AWS SDK for Java v2 Netty
    client does this by default."""
    server = serve_twisted_tls_server(TwistedGateway(protocol_gateway))

    context = stdlib_ssl.create_default_context()
    context.check_hostname = False
    context.verify_mode = stdlib_ssl.CERT_NONE
    if alpn:
        context.set_alpn_protocols(["h2"])

    with socket.create_connection((server.host, server.port), timeout=5) as raw_sock:
        with context.wrap_socket(raw_sock, server_hostname="localhost") as sock:
            status, body = _h2_get(sock, "https", "/protocol", fragment=fragment)

    assert status == 200
    assert json.loads(body) == {"protocol": "HTTP/2"}


@pytest.mark.parametrize("fragment", [False, True], ids=["whole", "fragmented"])
def test_http2_cleartext_prior_knowledge(serve_twisted_gateway, protocol_gateway, fragment):
    server = serve_twisted_gateway(protocol_gateway)

    with socket.create_connection((server.host, server.port), timeout=5) as sock:
        status, body = _h2_get(sock, "http", "/protocol", fragment=fragment)

    assert status == 200
    assert json.loads(body) == {"protocol": "HTTP/2"}


def _connect_protocol(
    gateway: Gateway,
) -> tuple[PriorKnowledgeHTTPChannelProtocol, StringTransport]:
    protocol = TwistedGateway(gateway).buildProtocol(IPv4Address("TCP", "127.0.0.1", 12345))
    # schedule the channels' timeouts on a fake clock instead of the reactor running in another thread
    protocol.callLater = Clock().callLater
    transport = StringTransport()
    protocol.makeConnection(transport)
    return protocol, transport


def test_http2_preface_received_byte_by_byte(protocol_gateway):
    protocol, transport = _connect_protocol(protocol_gateway)
    try:
        for i in range(len(H2_PREFACE)):
            assert not isinstance(protocol._channel, H2Connection)
            protocol.dataReceived(H2_PREFACE[i : i + 1])

        assert isinstance(protocol._channel, H2Connection)
        assert not transport.value().startswith(b"HTTP/")
    finally:
        protocol.connectionLost(Failure(ConnectionDone()))


def test_http1_request_starting_like_http2_preface(protocol_gateway):
    protocol, transport = _connect_protocol(protocol_gateway)
    try:
        protocol.dataReceived(b"PRI * HTTP/")
        assert transport.value() == b""

        protocol.dataReceived(b"1.1")

        assert isinstance(protocol._channel, HeaderPreservingHTTPChannel)
    finally:
        protocol.connectionLost(Failure(ConnectionDone()))
