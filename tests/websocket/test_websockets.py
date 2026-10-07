import json
import socket
import struct
import threading
import time
from queue import Queue

import pytest
import websocket
from _pytest.fixtures import SubRequest
from twisted.internet.threads import blockingCallFromThread
from twisted.python import threadable
from werkzeug.datastructures import Headers

from rolo import Response, Router
from rolo.serving.twisted import WebSocketChannel
from rolo.testing.pytest import poll_condition
from rolo.websocket.request import (
    WebSocketDisconnectedError,
    WebSocketProtocolError,
    WebSocketRequest,
)


@pytest.fixture(params=["asgi", "twisted"])
def serve_websocket_listener(request: SubRequest):
    def _serve(listener):
        if request.param == "asgi":
            srv = request.getfixturevalue("serve_asgi_adapter")
            return srv(wsgi_app=None, websocket_listener=listener)
        else:
            srv = request.getfixturevalue("serve_twisted_websocket_listener")
            return srv(listener)

    yield _serve


def test_websocket_basic_interaction(serve_websocket_listener):
    raised = threading.Event()

    @WebSocketRequest.listener
    def app(request: WebSocketRequest):
        with request.accept() as ws:
            ws.send("hello")
            assert ws.receive() == "foobar"
            ws.send("world")

        with pytest.raises(WebSocketDisconnectedError):
            ws.receive()

        raised.set()

    server = serve_websocket_listener(app)

    client = websocket.WebSocket()
    client.connect(server.url.replace("http://", "ws://"))
    assert client.recv() == "hello"
    client.send("foobar")
    assert client.recv() == "world"
    client.close()

    assert raised.wait(timeout=3)


def test_websocket_disconnect_while_iter(serve_websocket_listener):
    """Makes sure that the ``for line in iter(ws)`` pattern works smoothly when the client disconnects."""
    returned = threading.Event()
    received = []

    @WebSocketRequest.listener
    def app(request: WebSocketRequest):
        with request.accept() as ws:
            for line in iter(ws):
                received.append(line)

        returned.set()

    server = serve_websocket_listener(app)

    client = websocket.WebSocket()
    client.connect(server.url.replace("http://", "ws://"))

    client.send("foo")
    client.send("bar")
    client.close()

    assert returned.wait(timeout=3)
    assert received[0] == "foo"
    assert received[1] == "bar"


def test_close_handshake_client_initiated(serve_websocket_listener):
    """When the client sends a close frame, the server has to echo the close frame back to
    complete the closing handshake, and then terminate the TCP connection (RFC 6455 section 7)."""
    disconnected = threading.Event()

    @WebSocketRequest.listener
    def app(request: WebSocketRequest):
        with request.accept() as ws:
            with pytest.raises(WebSocketDisconnectedError):
                ws.receive()
        disconnected.set()

    server = serve_websocket_listener(app)

    client = websocket.WebSocket()
    client.connect(server.url.replace("http://", "ws://"))
    client.send_close(websocket.STATUS_NORMAL)

    frame = client.recv_frame()
    assert frame.opcode == websocket.ABNF.OPCODE_CLOSE
    assert struct.unpack("!H", frame.data[:2])[0] == websocket.STATUS_NORMAL

    client.sock.settimeout(5)
    assert client.sock.recv(1) == b"", "expected the server to terminate the TCP connection"
    assert disconnected.wait(timeout=3)


def test_close_code_and_reason_client_initiated(serve_twisted_websocket_listener):
    """The close code and reason sent by the client are surfaced through the
    ``WebSocketDisconnectedError``. Only tested with twisted, since hypercorn does not pass the client's
    close code or reason to the ASGI app."""
    errors = Queue()

    @WebSocketRequest.listener
    def app(request: WebSocketRequest):
        with request.accept() as ws:
            with pytest.raises(WebSocketDisconnectedError) as e:
                ws.receive()
            errors.put(e.value)

    server = serve_twisted_websocket_listener(app)

    client = websocket.WebSocket()
    client.connect(server.url.replace("http://", "ws://"))
    client.close(status=4001, reason=b"test reason")

    error = errors.get(timeout=3)
    assert error.code == 4001
    assert error.reason == "test reason"


def test_close_code_and_reason_after_iter(serve_twisted_websocket_listener):
    """The iterator ends silently on disconnect, but the client's close code and reason are kept on the
    ``WebSocket``. Only tested with twisted, see ``test_close_code_and_reason_client_initiated``."""
    closes = Queue()

    @WebSocketRequest.listener
    def app(request: WebSocketRequest):
        with request.accept() as ws:
            assert ws.close_code is None
            assert ws.close_reason is None
            for _ in iter(ws):
                pass
            closes.put((ws.close_code, ws.close_reason))

    server = serve_twisted_websocket_listener(app)

    client = websocket.WebSocket()
    client.connect(server.url.replace("http://", "ws://"))
    client.send("foo")
    client.close(status=4001, reason=b"test reason")

    assert closes.get(timeout=3) == (4001, "test reason")


def test_server_close_after_client_close(serve_twisted_websocket_listener, monkeypatch):
    """The server application closing the websocket after the client closed it must not fail, even when
    it runs before the reactor has finished the request of the completed closing handshake. The reactor is
    held in that window until the application has closed. Only tested with twisted, since the window is
    specific to its channel."""
    app_closed = threading.Event()
    results = Queue()

    original_close = WebSocketChannel.close

    def close(self):
        if threadable.isInIOThread():
            app_closed.wait(timeout=3)
        original_close(self)

    monkeypatch.setattr(WebSocketChannel, "close", close)

    @WebSocketRequest.listener
    def app(request: WebSocketRequest):
        try:
            with request.accept() as ws:
                with pytest.raises(WebSocketDisconnectedError):
                    ws.receive()
                ws.close()
        except Exception as e:
            results.put(e)
        else:
            results.put("ok")
        finally:
            app_closed.set()

    server = serve_twisted_websocket_listener(app)

    client = websocket.WebSocket()
    client.connect(server.url.replace("http://", "ws://"))
    client.close(status=4001, reason=b"test reason")

    assert results.get(timeout=5) == "ok"


def test_close_handshake_server_initiated(serve_websocket_listener):
    """When the server closes the websocket, the client has to receive a proper close frame. Once the client
    echoed it, the server has to terminate the TCP connection."""

    @WebSocketRequest.listener
    def app(request: WebSocketRequest):
        with request.accept() as ws:
            ws.send("hello")

    server = serve_websocket_listener(app)

    client = websocket.WebSocket()
    client.connect(server.url.replace("http://", "ws://"))
    assert client.recv() == "hello"

    frame = client.recv_frame()
    assert frame.opcode == websocket.ABNF.OPCODE_CLOSE
    client.send_close(status=struct.unpack("!H", frame.data[:2])[0])

    client.sock.settimeout(5)
    assert client.sock.recv(1) == b"", "expected the server to terminate the TCP connection"


def test_close_handshake_server_initiated_client_does_not_echo(
    serve_twisted_websocket_listener, monkeypatch
):
    """When the client never echoes the server's close frame, the server has to terminate the TCP connection
    after a timeout. Only tested with twisted, since the timeout is specific to its channel."""
    monkeypatch.setattr(WebSocketChannel, "closeTimeout", 0.5)

    @WebSocketRequest.listener
    def app(request: WebSocketRequest):
        with request.accept() as ws:
            ws.send("hello")

    server = serve_twisted_websocket_listener(app)

    client = websocket.WebSocket()
    client.connect(server.url.replace("http://", "ws://"))
    assert client.recv() == "hello"

    frame = client.recv_frame()
    assert frame.opcode == websocket.ABNF.OPCODE_CLOSE

    client.sock.settimeout(5)
    assert client.sock.recv(1) == b"", "expected the server to terminate the TCP connection"


def test_websocket_headers(serve_websocket_listener):
    @WebSocketRequest.listener
    def echo_headers(request: WebSocketRequest):
        with request.accept(headers=Headers({"x-foo-bar": "foobar"})) as ws:
            ws.send(json.dumps(dict(request.headers)))

    server = serve_websocket_listener(echo_headers)

    client = websocket.WebSocket()
    client.connect(
        server.url.replace("http://", "ws://"),
        header=["Authorization: Basic let-me-in", "CasedHeader: hello"],
    )

    assert client.handshake_response.status == 101
    assert client.getheaders()["x-foo-bar"] == "foobar"
    doc = client.recv()
    headers = json.loads(doc)
    assert headers["Connection"] == "Upgrade"
    assert headers["Authorization"] == "Basic let-me-in"
    assert headers["CasedHeader"] == "hello"


def test_websocket_reject(serve_websocket_listener):
    @WebSocketRequest.listener
    def respond(request: WebSocketRequest):
        request.reject(Response("nope", 403))

    server = serve_websocket_listener(respond)

    socket = websocket.WebSocket()
    with pytest.raises(websocket.WebSocketBadStatusException) as e:
        socket.connect(server.url.replace("http://", "ws://"))

    assert e.value.status_code == 403
    assert e.value.resp_body == b"nope"


def test_binary_and_text_mode(serve_websocket_listener):
    received = Queue()

    @WebSocketRequest.listener
    def echo_headers(request: WebSocketRequest):
        with request.accept() as ws:
            ws.send(b"foo")
            ws.send("textfoo")
            received.put(ws.receive())
            received.put(ws.receive())

    server = serve_websocket_listener(echo_headers)

    client = websocket.WebSocket()
    client.connect(server.url.replace("http://", "ws://"))

    assert client.handshake_response.status == 101
    data = client.recv()
    assert data == b"foo"

    data = client.recv()
    assert data == "textfoo"

    client.send("textbar")
    client.send_binary(b"bar")

    assert received.get(timeout=5) == "textbar"
    assert received.get(timeout=5) == b"bar"


def test_last_received_at_message(serve_websocket_listener):
    received_at = Queue()

    @WebSocketRequest.listener
    def app(request: WebSocketRequest):
        with request.accept() as ws:
            received_at.put(ws.last_received_at)
            ws.receive()
            received_at.put(ws.last_received_at)
            ws.send("done")

    server = serve_websocket_listener(app)

    client = websocket.WebSocket()
    client.connect(server.url.replace("http://", "ws://"))
    connected_at = received_at.get(timeout=5)
    sent_at = time.monotonic()
    client.send("foobar")
    assert client.recv() == "done"

    assert connected_at < sent_at <= received_at.get(timeout=5)
    client.close()


def test_last_received_at_ping(serve_twisted_websocket_listener):
    # ASGI servers answer pings without passing them on to the application
    activity = Queue()

    @WebSocketRequest.listener
    def app(request: WebSocketRequest):
        with request.accept() as ws:
            connected_at = ws.last_received_at
            activity.put(connected_at)
            poll_condition(lambda: ws.last_received_at > connected_at, timeout=5, interval=0.01)
            activity.put(ws.last_received_at)
            ws.receive()

    server = serve_twisted_websocket_listener(app)

    client = websocket.WebSocket()
    client.connect(server.url.replace("http://", "ws://"))
    connected_at = activity.get(timeout=5)
    pinged_at = time.monotonic()
    client.ping("ping")

    assert connected_at < pinged_at <= activity.get(timeout=5)
    client.send("done")
    client.close()


def test_receive_large_message(serve_websocket_listener):
    """A frame bigger than a single socket read must still be received as one message."""
    received = Queue()

    @WebSocketRequest.listener
    def app(request: WebSocketRequest):
        with request.accept() as ws:
            received.put(ws.receive())
            received.put(ws.receive())

    server = serve_websocket_listener(app)

    client = websocket.WebSocket()
    client.connect(server.url.replace("http://", "ws://"))
    client.send("x" * 1024 * 1024)
    client.send_binary(b"y" * 1024 * 1024)

    assert received.get(timeout=5) == "x" * 1024 * 1024
    assert received.get(timeout=5) == b"y" * 1024 * 1024
    client.close()


def test_receive_fragmented_message(serve_websocket_listener):
    """A message sent as several frames (RFC 6455 section 5.4) must be received as one message."""
    received = Queue()

    @WebSocketRequest.listener
    def app(request: WebSocketRequest):
        with request.accept() as ws:
            received.put(ws.receive())
            received.put(ws.receive())

    server = serve_websocket_listener(app)

    client = websocket.WebSocket()
    client.connect(server.url.replace("http://", "ws://"))
    client.send_frame(websocket.ABNF.create_frame("foo", websocket.ABNF.OPCODE_TEXT, fin=0))
    client.send_frame(websocket.ABNF.create_frame("bar", websocket.ABNF.OPCODE_CONT, fin=0))
    # control frames can be sent in the middle of a fragmented message
    client.ping("ping")
    client.send_frame(websocket.ABNF.create_frame("baz", websocket.ABNF.OPCODE_CONT, fin=1))
    client.send_frame(websocket.ABNF.create_frame(b"foo", websocket.ABNF.OPCODE_BINARY, fin=0))
    client.send_frame(websocket.ABNF.create_frame(b"bar", websocket.ABNF.OPCODE_CONT, fin=1))

    assert received.get(timeout=5) == "foobarbaz"
    assert received.get(timeout=5) == b"foobar"
    client.close()


def test_send_non_confirming_data(serve_websocket_listener):
    match = Queue()

    @WebSocketRequest.listener
    def echo_headers(request: WebSocketRequest):
        with request.accept() as ws:
            with pytest.raises(WebSocketProtocolError) as e:
                ws.send({"foo": "bar"})
            match.put(e)

    server = serve_websocket_listener(echo_headers)

    client = websocket.WebSocket()
    client.connect(server.url.replace("http://", "ws://"))

    e = match.get(timeout=5)
    assert e.match("Cannot send data type <class 'dict'> over websocket")


def test_router_integration(serve_websocket_listener):
    router = Router()

    def _handler(request: WebSocketRequest, request_args: dict):
        with request.accept() as ws:
            ws.send("foo")
            ws.send(f"id={request_args['id']}")
            ws.send(json.dumps(dict(request.headers)))

    router.add("/foo/<id>", _handler)

    server = serve_websocket_listener(WebSocketRequest.listener(router.dispatch))
    client = websocket.WebSocket()
    client.connect(
        server.url.replace("http://", "ws://") + "/foo/bar", header=["CasedHeader: hello"]
    )
    assert client.recv() == "foo"
    assert client.recv() == "id=bar"
    assert "CasedHeader" in json.loads(client.recv())


def test_send_many_messages(serve_websocket_listener):
    """Sending more data than the socket buffers hold must deliver every message intact and in order. The
    twisted listener runs in a threadpool thread, and writing to the transport directly from there races
    with the reactor flushing the same transport, which loses and reorders data."""
    messages = 10_000
    payload = "x" * 1024

    @WebSocketRequest.listener
    def app(request: WebSocketRequest):
        with request.accept() as ws:
            assert ws.receive() == "start"
            for i in range(messages):
                ws.send(f"{i:08d}{payload}")
            assert ws.receive() == "done"

    server = serve_websocket_listener(app)

    for _ in range(3):
        client = websocket.WebSocket()
        client.connect(server.url.replace("http://", "ws://"), timeout=5)
        client.send("start")
        for i in range(messages):
            assert client.recv() == f"{i:08d}{payload}"
        client.send("done")
        client.close()


def test_server_close_while_client_is_sending(serve_twisted_websocket_listener):
    """When the server closes the websocket while the client is still sending, the server has to wait for the
    client's close frame before terminating the TCP connection (RFC 6455 section 5.5.1). Terminating it right
    away leaves the client's frames unread on the server, which makes the kernel reset the connection, and the
    client loses the messages it has not read yet (RFC 6455 section 1.4). Only tested with twisted, since
    hypercorn terminates the TCP connection right away as well."""
    messages = 50_000

    @WebSocketRequest.listener
    def app(request: WebSocketRequest):
        with request.accept() as ws:
            assert ws.receive() == "start"
            for _ in range(messages):
                ws.send("x" * 32)

    server = serve_twisted_websocket_listener(app)

    for _ in range(3):
        client = websocket.WebSocket()
        client.connect(server.url.replace("http://", "ws://"), timeout=5)
        stop = threading.Event()

        def _ping(_client: websocket.WebSocket, _stop: threading.Event):
            while not _stop.is_set():
                try:
                    _client.ping(b"ping")
                except websocket.WebSocketException:
                    return
                time.sleep(0.001)

        pinger = threading.Thread(target=_ping, args=(client, stop), daemon=True)
        pinger.start()
        client.send("start")
        try:
            for _ in range(messages):
                assert client.recv_data(control_frame=False)[1] == b"x" * 32
        finally:
            stop.set()
            pinger.join()

        # the server may still answer pings it received before it sent its close frame
        opcode, _ = client.recv_data(control_frame=True)
        while opcode == websocket.ABNF.OPCODE_PONG:
            opcode, _ = client.recv_data(control_frame=True)
        assert opcode == websocket.ABNF.OPCODE_CLOSE
        client.close()


def test_server_close_client_stops_reading(
    twisted_reactor, serve_twisted_websocket_listener, monkeypatch
):
    """When the client stops reading after the server closed the websocket, the send buffer never drains, so
    neither the client's close frame nor the start of the close timeout ever comes. The server has to abort the
    TCP connection after ``closeAbortTimeout``. Only tested with twisted, since the timeout is specific to its
    channel."""
    monkeypatch.setattr(WebSocketChannel, "closeTimeout", 0.2)
    monkeypatch.setattr(WebSocketChannel, "closeAbortTimeout", 0.5)
    channels = Queue()

    @WebSocketRequest.listener
    def app(request: WebSocketRequest):
        with request.accept() as ws:
            channel = ws.socket.channel
            channels.put(channel)
            # small socket buffers, so the send buffer stays full while the client doesn't read
            blockingCallFromThread(
                twisted_reactor,
                channel.request.transport.socket.setsockopt,
                socket.SOL_SOCKET,
                socket.SO_SNDBUF,
                4096,
            )
            ws.send(b"x" * (8 * 1024 * 1024))

    server = serve_twisted_websocket_listener(app)

    client = websocket.WebSocket()
    client.connect(
        server.url.replace("http://", "ws://"),
        timeout=5,
        sockopt=[(socket.SOL_SOCKET, socket.SO_RCVBUF, 4096)],
    )
    try:
        channel = channels.get(timeout=5)
        transport = channel.request.transport
        assert poll_condition(
            lambda: blockingCallFromThread(twisted_reactor, lambda: transport.disconnected),
            timeout=5,
        ), "expected the server to abort the TCP connection"
    finally:
        client.shutdown()
