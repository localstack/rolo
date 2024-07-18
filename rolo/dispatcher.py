import inspect
import json
import logging
from typing import Any, Dict, Optional, Protocol, Type, Union

from werkzeug import Response as WerkzeugResponse

try:
    import pydantic

    ENABLE_PYDANTIC = True
except ImportError:
    ENABLE_PYDANTIC = False

from .request import Request
from .response import Response
from .router import Dispatcher, RequestArguments

LOG = logging.getLogger(__name__)

ResultValue = Union[
    WerkzeugResponse,
    str,
    bytes,
    Dict[str, Any],  # a JSON dict
    list[Any],
]


def _populate_response(
    response: WerkzeugResponse, result: ResultValue, json_encoder: Type[json.JSONEncoder]
):
    if result is None:
        return response

    elif isinstance(result, (str, bytes, bytearray)):
        response.data = result
    elif isinstance(result, (dict, list)):
        response.data = json.dumps(result, cls=json_encoder)
        response.mimetype = "application/json"
    else:
        raise ValueError("unhandled result type %s", type(result))

    return response


class Handler(Protocol):
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


def _try_parse_pydantic_request_body(request: Request, endpoint: Handler) -> Optional[dict]:
    if not request.content_length:
        return None

    if not inspect.isfunction(endpoint) and not inspect.ismethod(endpoint):
        # cannot yet dispatch to other callables (e.g. an object with a `__call__` method)
        return None

    # finds the first pydantic.BaseModel in the list of annotations.
    # ``def foo(request: Request, id: int, item: MyItem)`` would yield ``('my_item', MyItem)``
    arg_name = None
    arg_type = None
    for k, v in endpoint.__annotations__.items():
        if issubclass(v, pydantic.BaseModel):
            arg_name = k
            arg_type = v
            break

    if arg_type is None:
        return None

    # TODO: error handling
    obj = request.get_json(force=True)

    # TODO: error handling
    return {arg_name: arg_type.model_validate(obj)}


def handler_dispatcher(json_encoder: Type[json.JSONEncoder] = None) -> Dispatcher[Handler]:
    """
    Creates a Dispatcher that treats endpoints like callables of the ``Handler`` Protocol.

    :param json_encoder: optionally the json encoder class to use for translating responses
    :return: a new dispatcher
    """

    def _dispatch(request: Request, endpoint: Handler, args: RequestArguments) -> Response:
        if ENABLE_PYDANTIC:
            try:
                kwargs = _try_parse_pydantic_request_body(request, endpoint) or {}
                result = endpoint(request, **{**args, **kwargs})
            except pydantic.ValidationError as e:
                return Response(e.json(), mimetype="application/json", status=400)

            if isinstance(result, pydantic.BaseModel):
                result = result.model_dump()

        else:
            result = endpoint(request, **args)

        if isinstance(result, WerkzeugResponse):
            return result

        response = Response()
        if result is not None:
            _populate_response(response, result, json_encoder)
        return response

    return _dispatch
