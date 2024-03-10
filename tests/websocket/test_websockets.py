import json
import threading
from queue import Queue

import pytest
import websocket
from _pytest.fixtures import SubRequest
from werkzeug.datastructures import Headers

from rolo import Router
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


def test_websocket_headers(serve_websocket_listener):
    @WebSocketRequest.listener
    def echo_headers(request: WebSocketRequest):
        with request.accept(headers=Headers({"x-foo-bar": "foobar"})) as ws:
            ws.send(json.dumps(dict(request.headers)))

    server = serve_websocket_listener(echo_headers)

    client = websocket.WebSocket()
    client.connect(
        server.url.replace("http://", "ws://"), header=["Authorization: Basic let-me-in"]
    )

    assert client.handshake_response.status == 101
    assert client.getheaders()["x-foo-bar"] == "foobar"
    doc = client.recv()
    headers = json.loads(doc)
    assert headers["Connection"] == "Upgrade"
    assert headers["Authorization"] == "Basic let-me-in"


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


def test_router_integration(serve_asgi_adapter):
    router = Router()

    def _handler(request: WebSocketRequest, request_args: dict):
        with request.accept() as ws:
            ws.send("foo")
            ws.send(f"id={request_args['id']}")

    router.add("/foo/<id>", _handler)

    server = serve_asgi_adapter(
        wsgi_app=None,
        websocket_listener=WebSocketRequest.listener(router.dispatch),
    )
    client = websocket.WebSocket()
    client.connect(server.url.replace("http://", "ws://") + "/foo/bar")
    assert client.recv() == "foo"
    assert client.recv() == "id=bar"
