"""Several gateway handlers"""
import typing as t

from werkzeug.datastructures import Headers
from werkzeug.exceptions import HTTPException, NotFound

from rolo.response import Response
from rolo.router import Router

from .chain import HandlerChain, RequestContext


class RouterHandler:
    """
    Adapter to serve a ``Router`` as a ``Handler``.
    """

    router: Router
    respond_not_found: bool

    def __init__(self, router: Router, respond_not_found: bool = False) -> None:
        self.router = router
        self.respond_not_found = respond_not_found

    def __call__(self, chain: HandlerChain, context: RequestContext, response: Response):
        try:
            router_response = self.router.dispatch(context.request)
            response.update_from(router_response)
            chain.stop()
        except NotFound:
            if self.respond_not_found:
                chain.respond(404, "not found")


class EmptyResponseHandler:
    """
    Handler that creates a default response if the response in the context is empty.
    """

    status_code: int
    body: bytes
    headers: dict

    def __init__(self, status_code: int = 404, body: bytes = None, headers: Headers = None):
        self.status_code = status_code
        self.body = body or b""
        self.headers = headers or Headers()

    def __call__(self, chain: HandlerChain, context: RequestContext, response: Response):
        if self.is_empty_response(response):
            self.populate_default_response(response)

    def is_empty_response(self, response: Response):
        return response.status_code in [0, None] and not response.response

    def populate_default_response(self, response: Response):
        response.status_code = self.status_code
        response.data = self.body
        response.headers.update(self.headers)


class WerkzeugExceptionHandler:
    def __init__(self, output_format: t.Literal["json", "html"] = None) -> None:
        self.format = output_format or "json"

    def __call__(
        self, chain: HandlerChain, exception: Exception, context: RequestContext, response: Response
    ):
        if not isinstance(exception, HTTPException):
            return

        headers = Headers(exception.get_headers())  # FIXME
        headers.pop()

        if self.format == "html":
            chain.respond(status_code=exception.code, headers=headers, payload=exception.get_body())
        elif self.format == "json":
            chain.respond(
                status_code=exception.code,
                headers=headers,
                payload={"code": exception.code, "description": exception.description},
            )
        else:
            raise ValueError(f"unknown rendering format {self.format}")
