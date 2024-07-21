import json
import logging
import typing as t

from werkzeug import Response as WerkzeugResponse

try:
    import pydantic  # noqa

    ENABLE_PYDANTIC = True
except ImportError:
    ENABLE_PYDANTIC = False

from rolo.request import Request
from rolo.response import Response

from .router import Dispatcher, RequestArguments

LOG = logging.getLogger(__name__)

ResultValue = t.Union[
    WerkzeugResponse,
    str,
    bytes,
    dict[str, t.Any],  # a JSON dict
    list[t.Any],
]


class Handler(t.Protocol):
    """
    A protocol used by a ``Router`` together with the dispatcher created with ``handler_dispatcher``. Endpoints added
    with this protocol take as first argument the HTTP request object, and then as keyword arguments the request
    parameters added in the rule. This makes it work very similar to flask routes.

    Example code could look like this::

        def my_route(request: Request, organization: str, repo: str):
            return {"something": "returned as json response"}

        router = Router(dispatcher=handler_dispatcher)
        router.add("/<organization>/<repo>", endpoint=my_route)

    """

    def __call__(self, request: Request, **kwargs) -> ResultValue:
        """
        Handle the given request.

        :param request: the HTTP request object
        :param kwargs: the url request parameters
        :return: a string or bytes value, a dict to create a json response, or a raw werkzeug Response object.
        """
        raise NotImplementedError


class HandlerDispatcher:
    def __init__(self, json_encoder: t.Type[json.JSONEncoder] = None):
        self.json_encoder = json_encoder

    def __call__(
        self, request: Request, endpoint: t.Callable, request_args: RequestArguments
    ) -> Response:
        result = self.invoke_endpoint(request, endpoint, request_args)
        return self.to_response(result)

    def invoke_endpoint(
        self,
        request: Request,
        endpoint: t.Callable,
        request_args: RequestArguments,
    ) -> t.Any:
        return endpoint(request, **request_args)

    def to_response(self, value: ResultValue) -> Response:
        if isinstance(value, WerkzeugResponse):
            return value

        response = Response()
        if value is None:
            return response

        self.populate_response(response, value)
        return response

    def populate_response(self, response: Response, value: ResultValue):
        if isinstance(value, (str, bytes, bytearray)):
            response.data = value
        elif isinstance(value, (dict, list)):
            response.data = json.dumps(value, cls=self.json_encoder)
            response.mimetype = "application/json"
        else:
            raise ValueError("unhandled result type %s", type(value))


def handler_dispatcher(json_encoder: t.Type[json.JSONEncoder] = None) -> Dispatcher[Handler]:
    """
    Creates a Dispatcher that treats endpoints like callables of the ``Handler`` Protocol.

    :param json_encoder: optionally the json encoder class to use for translating responses
    :return: a new dispatcher
    """
    if ENABLE_PYDANTIC:
        from rolo.routing.pydantic import PydanticHandlerDispatcher

        return PydanticHandlerDispatcher(json_encoder)

    return HandlerDispatcher(json_encoder)
