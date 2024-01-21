import typing as t

from werkzeug.datastructures import Headers, MultiDict
from werkzeug.wrappers import Request

from rolo.response import Response

if t.TYPE_CHECKING:
    from _typeshed.wsgi import StartResponse, WSGIEnvironment

import logging

from .gateway import Gateway

LOG = logging.getLogger(__name__)


class WsgiGateway:
    """
    Exposes a ``Gateway`` as a WSGI application.
    """

    gateway: Gateway

    def __init__(self, gateway: Gateway) -> None:
        super().__init__()
        self.gateway = gateway

    def __call__(
        self, environ: "WSGIEnvironment", start_response: "StartResponse"
    ) -> t.Iterable[bytes]:
        # create request from environment
        LOG.debug(
            "%s %s%s",
            environ["REQUEST_METHOD"],
            environ.get("HTTP_HOST"),
            environ.get("RAW_URI"),
        )
        request = Request(environ)
        if "asgi.headers" in environ:
            # restores raw headers from ASGI scope, which allows dashes in header keys
            # see https://github.com/pallets/werkzeug/issues/940

            request.headers = Headers(
                MultiDict(
                    [
                        (k.decode("latin-1"), v.decode("latin-1"))
                        for (k, v) in environ["asgi.headers"]
                    ]
                )
            )
        else:
            # by default, werkzeug requests from environ are immutable
            request.headers = Headers(request.headers)

        # prepare response
        response = Response()

        self.gateway.process(request, response)

        return response(environ, start_response)
