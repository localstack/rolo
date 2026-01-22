"""Several gateway handlers"""
import typing as t

from werkzeug.datastructures import Headers, MultiDict
from werkzeug.exceptions import HTTPException, NotFound

from rolo.response import Response
from rolo.routing import Router

from .chain import HandlerChain, RequestContext


class RouterHandler:
    """
    Adapter to serve a ``Router`` as a ``Handler``. The handler takes from the ``RequestContext`` the ``Request``
    object, and dispatches it via ``Router.dispatch``. The ``Response`` object that call returns, is then merged into
    the ``Response`` object managed by the handler chain. If the router returns a response, the ``HandlerChain`` is
    stopped.

    If the dispatching raises a ``NotFound`` (because there is no route in the Router to match the request), the chain
    will respond with 404 and "not found" as string, given that ``respond_not_found`` is set to True. This is to
    provide a simple, default way to handle 404 messages. In most cases, you will want your own 404 error handling
    in the handler chain, which is why ``respond_not_found`` is set to ``False`` by default.
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
    Handler that creates a default response if the response in the context is empty. A response is considered empty
    if its status code is set to 0 or None, and the response body is empty. Since ``Response`` is initialized with a
    200 status code by default, you'll have to explicitly set the status code to 0 or None in your handler chain.
    For example::

        def init_response(chain, context, response):
            response.status_code = 0

        def handle_request(chain, context, response):
            if context.request.path == "/hello"
                chain.respond("hello world")

        gateway = Gateway(request_handlers=[
            init_response,
            handle_request,
            EmptyResponseHandler(404, body=b"not found")
        ])

    This handler chain will return 404 for all requests except those going to ``http://<server>/hello``.
    """

    status_code: int
    body: bytes
    headers: t.Mapping[str, t.Any] | MultiDict[str, t.Any] | Headers

    def __init__(self, status_code: int = 404, body: bytes = None, headers: Headers = None):
        """
        Creates a new EmptyResponseHandler that will populate the ``Response`` object with the given values, if the
        response was previously considered empty.

        :param status_code: The HTTP status code to use (defaults to 404)
        :param body: The body to use as response (defaults to empty string)
        :param headers: The additional headers to set for the response
        """
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
    """
    Convenience handler that translates werkzeug exceptions into HTML or JSON responses. Werkzeug exceptions are
    raised by ``Router`` instances, but can also be useful to use in your own handlers. These exceptions already
    contain a human-readable name, description, and an HTML template that can be rendered. The handler also supports
    a rolo-specific JSON format.

    For example, this handler chain::

        from werkzeug.exceptions import NotFound

        def raise_not_found(chain, context, response):
            raise NotFound()

        gateway = Gateway(
            request_handlers=[
                raise_not_found,
            ],
            exception_handlers=[
                WerkzeugExceptionHandler(output_format="html"),
            ]
        )

    Would always yield the following HTML::

        <!doctype html>
        <html lang=en>
        <title>404 Not Found</title>
        <h1>Not Found</h1>
        The requested URL was not found on the server. If you entered the URL manually please check
        your spelling and try again.

    Or if you use JSON (via ``WerkzeugExceptionHandler(output_format="json")``)::

        {
          "code": 404,
          "description": "The requested URL was not found on the server. [...]"
        }
    """

    def __init__(self, output_format: t.Literal["json", "html"] = None) -> None:
        """
        Create a new ``WerkzeugExceptionHandler`` to use as exception handler in a handler chain.

        :param output_format: The output format in which to render the exception into the response (either ``html``
            or ``json``), defaults to ``json``.
        """
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
                # TODO: add name
                payload={"code": exception.code, "description": exception.description},
            )
        else:
            raise ValueError(f"unknown rendering format {self.format}")
