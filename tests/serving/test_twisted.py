import datetime
import http.client
import io
import json
import ssl as stdlib_ssl

import pytest
import requests
import websocket
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID
from twisted.internet import ssl
from twisted.protocols.tls import TLSMemoryBIOFactory
from twisted.web.http_headers import Headers as TwistedHeaders
from twisted.web.server import Site
from wsproto import ConnectionType, WSConnection, events
from wsproto.connection import ConnectionState

from rolo import Request, Router, route
from rolo.dispatcher import handler_dispatcher
from rolo.gateway import Gateway
from rolo.gateway.handlers import RouterHandler
from rolo.serving.twisted import (
    HeaderPreservingHTTPChannel,
    HeaderPreservingWSGIResource,
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
def serve_twisted_tls_websocket_listener(twisted_reactor, self_signed_cert):
    """Like ``serve_twisted_websocket_listener``, but serves the listener over TLS."""
    ports = []

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

        cert_pem, key_pem = self_signed_cert
        certificate = ssl.PrivateCertificate.loadPEM(cert_pem + key_pem)
        factory = TLSMemoryBIOFactory(certificate.options(), False, site)

        port = get_random_tcp_port()
        ports.append(twisted_reactor.listenTCP(port, factory))
        srv = _ServerInfo("localhost", port, f"wss://localhost:{port}")
        assert wait_server_is_up(srv), f"gave up waiting for {srv}"
        return srv

    yield _create

    for _port in ports:
        _port.stopListening()


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
