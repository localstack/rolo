Websockets
==========

Rolo supports Websockets through ASGI and Twisted (see [serving](serving.md)).

## Websocket requests

Rolo introduces an HTTP method called `WEBSOCKET`, which can be used to register routes that deal with websocket
requests.

```python
from rolo import route
from rolo.websocket import WebSocketRequest


@route("/stream", methods=["WEBSOCKET"])
def handler(request: WebSocketRequest, name: str):
    ...
```

You can add such a route `Router`, but the Router needs to be handled through a `Gateway` using the `RouterHandler`, and
served through an ASGI webserver or twisted.

With a tool like [websocat](https://github.com/vi/websocat), you could now connect to the websocket.

### Accepting or rejecting the connection

The websocket connection needs to be either accepted or rejected via `WebSocketRequest`.
When calling ``WebSocketRequest.accept``, an upgrade response will be sent to the client, and the protocol will be
switched to the bidirectional WebSocket protocol.
If ``WebSocketRequest.reject`` is called, the server immediately returns an HTTP response and closes the connection.

You may want to do this when doing authorization for example:

```python
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
```

## Websocket object

`WebSocketRequest.accept` also returns a `WebSocket` object, that can then be used to send and receive data

You can explicitly call `WebSocket.receive`, or you can simply iterate over the `WebSocket` object.
Here is an example:

```python

from rolo import route
from rolo.websocket import WebSocketRequest


@route("/echo/<name>", methods=["WEBSOCKET"])
def handler(request: WebSocketRequest, name: str):
    with request.accept() as websocket:
        websocket.send(f"thanks for connecting {name}")
        for line in websocket:
            websocket.send(f"echo: {line}")
            if line == "exit":
                websocket.send("ok bye!")
                return
```
