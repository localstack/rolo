import pytest
import websocket

from rolo import Router, route
from rolo.gateway import Gateway
from rolo.gateway.handlers import RouterHandler
from rolo.websocket.request import WebSocketRequest


@pytest.mark.parametrize("serve_gateway", ["asgi", "twisted"], indirect=True)
def test_gateway_router_websocket_integration(serve_gateway):
    @route("/ws", methods=["WEBSOCKET"])
    def _handler(request: WebSocketRequest, args):
        with request.accept() as ws:
            ws.send("hello")
            ws.send(ws.receive())

    router = Router()
    router.add(_handler)

    server = serve_gateway(Gateway(request_handlers=[RouterHandler(router)]))

    client = websocket.WebSocket()
    client.connect(server.url.replace("http://", "ws://") + "/ws")

    assert client.recv() == "hello"
    client.send("foobar")
    assert client.recv() == "foobar"
    client.close()
