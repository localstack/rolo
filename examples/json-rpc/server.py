import dataclasses
import json
import logging
from typing import Callable

from werkzeug.exceptions import BadRequest
from werkzeug.serving import run_simple

from rolo import Response
from rolo.gateway import Gateway, HandlerChain, RequestContext
from rolo.gateway.wsgi import WsgiGateway

LOG = logging.getLogger(__name__)


@dataclasses.dataclass
class RpcRequest:
    jsonrpc: str
    method: str
    id: str | int | None
    params: dict | list | None = None


class RpcError(Exception):
    code: int
    message: str


class ParseError(RpcError):
    code = -32700
    message = "Parse error"


class InvalidRequest(RpcError):
    code = -32600
    message = "Invalid params"


class MethodNotFoundError(RpcError):
    code = -32601
    message = "Method not found"


class InternalError(RpcError):
    code = -32603
    message = "Internal error"


def parse_request(chain: HandlerChain, context: RequestContext, response: Response):
    context.rpc_request_id = None

    try:
        doc = context.request.get_json()
    except BadRequest as e:
        raise ParseError() from e

    try:
        context.rpc_request_id = doc["id"]
        context.rpc_request = RpcRequest(
            doc["jsonrpc"],
            doc["method"],
            doc["id"],
            doc.get("params"),
        )
    except KeyError as e:
        raise ParseError() from e


def log_request(chain: HandlerChain, context: RequestContext, response: Response):
    if context.rpc_request:
        LOG.info("RPC request object: %s", context.rpc_request)


def serialize_rpc_error(
        chain: HandlerChain,
        exception: Exception,
        context: RequestContext,
        response: Response,
):
    if not isinstance(exception, RpcError):
        return

    response.set_json(
        {
            "jsonrpc": "2.0",
            "error": {"code": exception.code, "message": exception.message},
            "id": context.rpc_request_id,
        }
    )


def log_exception(
        chain: HandlerChain,
        exception: Exception,
        context: RequestContext,
        response: Response,
):
    LOG.error("Exception in handler chain", exc_info=exception)


class Registry:
    methods: dict[str, Callable]

    def __init__(self, methods: dict[str, Callable]):
        self.methods = methods

    def __call__(
            self, chain: HandlerChain, context: RequestContext, response: Response
    ):
        try:
            context.method = self.methods[context.rpc_request.method]
        except KeyError as e:
            raise MethodNotFoundError() from e


def dispatch(chain: HandlerChain, context: RequestContext, response: Response):
    request: RpcRequest = context.rpc_request

    if isinstance(request.params, list):
        args = request.params
        kwargs = {}
    elif isinstance(request.params, dict):
        args = []
        kwargs = request.params
    else:
        raise InvalidRequest()

    try:
        context.result = context.method(*args, **kwargs)
    except RpcError:
        # if the method raises an RpcError, just re-raise it since it will be handled later
        raise
    except Exception as e:
        # all other exceptions are considered unhandled and therefore "Internal"
        raise InternalError() from e


def serialize_result(chain: HandlerChain, context: RequestContext, response: Response):
    if not context.rpc_request_id:
        # this is a notification, so we don't want to respond
        return

    response.set_json(
        {
            "jsonrpc": "2.0",
            "result": json.dumps(context.result),
            "id": context.rpc_request_id,
        }
    )


def main():
    logging.basicConfig(level=logging.DEBUG)

    def subtract(subtrahend: int, minuend: int):
        return subtrahend - minuend

    locate_method = Registry(
        {
            "subtract": subtract,
        }
    )

    gateway = Gateway(
        request_handlers=[
            parse_request,
            log_request,
            locate_method,
            dispatch,
        ],
        exception_handlers=[
            log_exception,
            serialize_rpc_error,
        ],
    )

    run_simple("localhost", 8000, WsgiGateway(gateway))


if __name__ == "__main__":
    main()
