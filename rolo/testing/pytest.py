"""rolo pytest plugin used both for internal testing and as testing library."""
import asyncio
import dataclasses
import socket
import threading
import time
import typing
from typing import Protocol

import pytest
from werkzeug import Request as WerkzeugRequest
from werkzeug import serving

from rolo import Router
from rolo.asgi import ASGIAdapter, ASGILifespanListener, WebSocketListener
from rolo.dispatcher import handler_dispatcher
from rolo.gateway import Gateway
from rolo.gateway.asgi import AsgiGateway
from rolo.gateway.wsgi import WsgiGateway

if typing.TYPE_CHECKING:
    from hypercorn.typing import ASGIFramework


class Server(Protocol):
    url: str
    host: str
    port: int

    def shutdown(self):
        ...


@dataclasses.dataclass
class _ServerInfo:
    host: str
    port: int
    url: str


@pytest.fixture
def serve_wsgi_app():
    servers: list[serving.BaseWSGIServer] = []

    def _serve(app, host: str = "localhost", port: int = None) -> serving.BaseWSGIServer | Server:
        srv = serving.make_server(host, port or 0, app, threaded=True)
        name = threading._newname("test-server-%d")
        threading.Thread(target=srv.serve_forever, name=name, daemon=True).start()
        servers.append(srv)
        srv.url = f"http://{srv.host}:{srv.port}"
        return srv

    yield _serve

    for server in servers:
        server.shutdown()


@pytest.fixture
def wsgi_router_server(serve_wsgi_app) -> tuple[Router, serving.BaseWSGIServer | Server]:
    """Creates a new Router with a handler dispatcher, serves it through a newly created ASGI server, and returns
    both the router and the server.
    """
    router = Router(dispatcher=handler_dispatcher())
    app = WerkzeugRequest.application(router.dispatch)
    return router, serve_wsgi_app(app)


@pytest.fixture()
def serve_asgi_app():
    import hypercorn
    import hypercorn.asyncio

    _server_shutdown = []

    def _create(
        app: "ASGIFramework",
        config: hypercorn.Config = None,
        event_loop: asyncio.AbstractEventLoop = None,
    ) -> Server:
        host = "localhost"
        port = get_random_tcp_port()
        bind = f"localhost:{port}"

        if not config:
            config = hypercorn.Config()
            config.h11_pass_raw_headers = True
            config.bind = [bind]

        event_loop = event_loop or asyncio.new_event_loop()
        close = asyncio.Event()
        closed = threading.Event()

        async def _set_close():
            close.set()

        def _run():
            event_loop.run_until_complete(
                hypercorn.asyncio.serve(app, config, shutdown_trigger=close.wait)
            )
            closed.set()

        def _shutdown():
            if close.is_set():
                return
            asyncio.run_coroutine_threadsafe(_set_close(), event_loop)
            closed.wait(timeout=10)
            try:
                app.close()
            except AttributeError:
                pass
            asyncio.run_coroutine_threadsafe(event_loop.shutdown_asyncgens(), event_loop)
            event_loop.shutdown_default_executor()
            event_loop.stop()
            event_loop.close()

        _server_shutdown.append(_shutdown)
        threading.Thread(
            target=_run, name=threading._newname("asgi-server-%d"), daemon=True
        ).start()

        srv = _ServerInfo(host, port, f"http://{host}:{port}")
        srv.shutdown = _shutdown

        assert poll_condition(
            lambda: is_server_up(srv), timeout=5, interval=0.1
        ), f"gave up waiting for server {srv}"

        return srv

    yield _create

    for server_shutdown in _server_shutdown:
        server_shutdown()


@pytest.fixture()
def serve_asgi_adapter(serve_asgi_app):
    def _create(
        wsgi_app,
        lifespan_listener: ASGILifespanListener = None,
        websocket_listener: WebSocketListener = None,
    ):
        loop = asyncio.new_event_loop()
        return serve_asgi_app(
            ASGIAdapter(
                wsgi_app,
                event_loop=loop,
                lifespan_listener=lifespan_listener,
                websocket_listener=websocket_listener,
            ),
            event_loop=loop,
        )

    yield _create


@pytest.fixture
def serve_wsgi_gateway(serve_wsgi_app):
    def _serve(gateway: Gateway) -> Server:
        return serve_wsgi_app(WsgiGateway(gateway))

    return _serve


@pytest.fixture
def serve_asgi_gateway(serve_asgi_app):
    def _serve(gateway: Gateway) -> Server:
        loop = asyncio.new_event_loop()
        return serve_asgi_app(AsgiGateway(gateway, event_loop=loop), event_loop=loop)

    return _serve


def is_server_up(srv: Server):
    args = socket.getaddrinfo(srv.host, srv.port, socket.AF_INET, socket.SOCK_STREAM)
    for family, socktype, proto, _canonname, sockaddr in args:
        s = socket.socket(family, socktype, proto)
        try:
            s.connect(sockaddr)
        except socket.error:
            return False
        else:
            s.close()
            return True


def get_random_tcp_port() -> int:
    import socket

    sock = socket.socket()
    sock.bind(("", 0))
    return sock.getsockname()[1]


def poll_condition(
    condition: typing.Callable[[], bool],
    timeout: float = None,
    interval: float = 0.5,
) -> bool:
    """
    Poll evaluates the given condition until a truthy value is returned. It does this every `interval` seconds
    (0.5 by default), until the timeout (in seconds, if any) is reached.

    Poll returns True once `condition()` returns a truthy value, or False if the timeout is reached.
    """
    remaining = 0
    if timeout is not None:
        remaining = timeout

    while not condition():
        if timeout is not None:
            remaining -= interval

            if remaining <= 0:
                return False

        time.sleep(interval)

    return True
