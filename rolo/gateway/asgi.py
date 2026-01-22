"""This module provides adapter code to expose a ``Gateway`` as an ASGI compatible application."""
import asyncio
import concurrent.futures.thread
from asyncio import AbstractEventLoop
from typing import Optional

from rolo.asgi import ASGIAdapter, ASGILifespanListener
from rolo.websocket.adapter import WebSocketListener
from rolo.websocket.request import WebSocketRequest

from .gateway import Gateway
from .wsgi import WsgiGateway


class _ThreadPool(concurrent.futures.thread.ThreadPoolExecutor):
    """
    This thread pool executor removes the threads it creates from the global ``_thread_queues`` of
    ``concurrent.futures.thread``, which joins all created threads at python exit and will block interpreter shutdown if
    any threads are still running, even if they are daemon threads.
    """

    def _adjust_thread_count(self) -> None:
        super()._adjust_thread_count()

        for t in self._threads:
            if not t.daemon:
                continue
            try:
                del concurrent.futures.thread._threads_queues[t]
            except KeyError:
                pass


class AsgiGateway:
    """
    Exposes a Gateway as an ASGI3 application. Under the hood, it uses a ``WsgiGateway`` with a threading async/sync
    bridge.
    """

    default_thread_count = 1000

    gateway: Gateway

    def __init__(
        self,
        gateway: Gateway,
        event_loop: Optional[AbstractEventLoop] = None,
        threads: int = None,
        lifespan_listener: Optional[ASGILifespanListener] = None,
        websocket_listener: Optional[WebSocketListener] = None,
    ) -> None:
        """
        Wrap a ``Gateway`` and expose it as an ASGI3 application.

        :param gateway: The Gateway instance to serve
        :param event_loop: optionally, you can pass your own event loop that is used by the gateway to process
            requests. By default, the global event loop via ``asyncio.get_event_loop()`` will be used.
        :param threads: Max number of threads used by the thread pool that is used to execute co-routines. Defaults to
            ``AsgiGateway.default_thread_count`` set to 1000.
        :param lifespan_listener: Optional ``ASGILifespanListener`` callback that is called on ASGI webserver lifecycle
            events.
        :param websocket_listener: Optional ``WebSocketListener``, a rolo callback that handles incoming websocket
            connections. By default, the listener invokes ``Gateway.accept``, so there's rarely a reason you would need
            a custom one.
        """
        self.gateway = gateway

        self.event_loop = event_loop or asyncio.get_event_loop()
        self.executor = _ThreadPool(
            threads or self.default_thread_count, thread_name_prefix="asgi_gw"
        )
        self.adapter = ASGIAdapter(
            WsgiGateway(gateway),
            event_loop=event_loop,
            executor=self.executor,
            lifespan_listener=lifespan_listener,
            websocket_listener=websocket_listener or WebSocketRequest.listener(gateway.accept),
        )
        self._closed = False

    async def __call__(self, scope, receive, send) -> None:
        """
        ASGI3 application interface.

        :param scope: the ASGI request scope
        :param receive: the receive callable
        :param send: the send callable
        """
        if self._closed:
            raise RuntimeError("Cannot except new request on closed ASGIGateway")

        return await self.adapter(scope, receive, send)

    def close(self):
        """
        Close the ASGIGateway by shutting down the underlying executor.
        """
        self._closed = True
        self.executor.shutdown(wait=False, cancel_futures=True)
