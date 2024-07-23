import inspect
import typing as t

import pydantic

from rolo.request import Request
from rolo.response import Response

from .handler import Handler, HandlerDispatcher, ResultValue
from .router import RequestArguments


def _get_model_argument(endpoint: Handler) -> t.Optional[tuple[str, t.Type[pydantic.BaseModel]]]:
    """
    Inspects the endpoint function using Python reflection to find in its signature a ``pydantic.BaseModel`` attribute.

    :param endpoint: the endpoint to inspect
    :return: a tuple containing the name and class, or None
    """
    if not inspect.isfunction(endpoint) and not inspect.ismethod(endpoint):
        # cannot yet dispatch to other callables (e.g. an object with a `__call__` method)
        return None

    # finds the first pydantic.BaseModel in the list of annotations.
    # ``def foo(request: Request, id: int, item: MyItem)`` would yield ``('my_item', MyItem)``
    for arg_name, arg_type in endpoint.__annotations__.items():
        if arg_name in ("self", "return"):
            continue
        if not inspect.isclass(arg_type):
            continue
        try:
            if issubclass(arg_type, pydantic.BaseModel):
                return arg_name, arg_type
        except TypeError:
            # FIXME: this is needed for Python 3.10 support
            continue

    return None


def _try_parse_pydantic_request_body(
    request: Request, endpoint: Handler
) -> t.Optional[tuple[str, pydantic.BaseModel]]:
    arg = _get_model_argument(endpoint)

    if not arg:
        return

    arg_name, arg_type = arg

    if not request.content_length:
        # forces a ValidationError "Invalid JSON: EOF while parsing a value at line 1 column 0"
        arg_type.model_validate_json(b"")

    # will raise a werkzeug.BadRequest error if the JSON is invalid
    obj = request.get_json(force=True)

    return arg_name, arg_type.model_validate(obj)


class PydanticHandlerDispatcher(HandlerDispatcher):
    """
    Special HandlerDispatcher that knows how to serialize and deserialize pydantic models.
    """

    def invoke_endpoint(
        self,
        request: Request,
        endpoint: t.Callable,
        request_args: RequestArguments,
    ) -> t.Any:
        # prepare request args
        try:
            arg = _try_parse_pydantic_request_body(request, endpoint)
        except pydantic.ValidationError as e:
            return Response(e.json(), mimetype="application/json", status=400)

        if arg:
            arg_name, model = arg
            request_args = {**request_args, arg_name: model}

        return super().invoke_endpoint(request, endpoint, request_args)

    def populate_response(self, response: Response, value: ResultValue):
        # try to convert any pydantic types to dicts before handing them to the parent implementation
        if isinstance(value, pydantic.BaseModel):
            value = value.model_dump()
        elif isinstance(value, (list, tuple)):
            converted = []
            for element in value:
                if isinstance(element, pydantic.BaseModel):
                    converted.append(element.model_dump())
                else:
                    converted.append(element)
            value = converted

        super().populate_response(response, value)
