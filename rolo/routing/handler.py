import inspect
import json
import logging
import typing as t
from typing import get_origin

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


def _is_typeddict(annotation: t.Any) -> bool:
    """Check if a type annotation is a TypedDict."""
    try:
        # TypedDict classes have __annotations__ and __total__ attributes
        return (
            isinstance(annotation, type)
            and hasattr(annotation, "__annotations__")
            and hasattr(annotation, "__total__")
            and hasattr(annotation, "__required_keys__")
        )
    except Exception:
        return False


def _validate_typeddict(data: dict, typeddict_class: type) -> tuple[dict, list[str]]:
    """
    Validate a dict against a TypedDict schema.

    Returns (validated_data, errors) where errors is a list of validation error messages.
    """
    errors = []
    validated = {}

    # Get required and optional keys
    required_keys = getattr(typeddict_class, "__required_keys__", set())
    annotations = getattr(typeddict_class, "__annotations__", {})

    # Check for missing required keys
    for key in required_keys:
        if key not in data:
            errors.append(f"Missing required field: '{key}'")

    # Check for unexpected keys
    for key in data:
        if key not in annotations:
            errors.append(f"Unexpected field: '{key}'")

    # Basic type checking for present keys
    for key, value in data.items():
        if key in annotations:
            expected_type = annotations[key]
            validated[key] = value

            # Handle Literal types
            origin = get_origin(expected_type)
            if origin is t.Literal:
                from typing import get_args
                allowed_values = get_args(expected_type)
                if value not in allowed_values:
                    errors.append(f"Field '{key}': value must be one of {allowed_values}, got '{value}'")

    return validated, errors

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
        # Check if endpoint has TypedDict parameters for request body parsing
        sig = inspect.signature(endpoint)

        # Look for TypedDict parameters (excluding 'self', 'request', 'cls')
        for param_name, param in sig.parameters.items():
            if param_name in ("self", "request", "cls"):
                continue

            # Skip if parameter is already in request_args (path parameters)
            if param_name in request_args:
                continue

            param_type = param.annotation
            if param_type is inspect.Parameter.empty:
                continue

            # Check if it's a TypedDict
            if _is_typeddict(param_type):
                # Parse request body JSON
                try:
                    data = request.get_json(force=True, silent=False)
                except Exception as e:
                    # Return 400 if JSON parsing fails
                    from werkzeug.exceptions import BadRequest
                    raise BadRequest(f"Invalid JSON in request body: {e}")

                if not isinstance(data, dict):
                    from werkzeug.exceptions import BadRequest
                    raise BadRequest("Request body must be a JSON object")

                # Validate against TypedDict schema
                validated_data, errors = _validate_typeddict(data, param_type)

                if errors:
                    from werkzeug.exceptions import BadRequest
                    error_msg = "Request body validation failed:\n" + "\n".join(f"  - {err}" for err in errors)
                    raise BadRequest(error_msg)

                # Inject validated data into request_args
                request_args = {**request_args, param_name: validated_data}
                break  # Only handle one request body parameter

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
