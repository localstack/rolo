# Tutorial: JSON-RPC Server

In this tutorial, we will build a JSON-RPC over HTTP protocol server using the rolo handler chain framework.
It's a very simple protocol, making it an excellent playground to learn about rolo.
After reading the tutorial, you'll have a good understanding of the handler chain concept,
how to decompose your server application into modular handlers,
and how error handling works in the handler chain.
You'll be left with a few gaps in the implementation that you can explore yourself.

## Introduction

[JSON-RPC](https://www.jsonrpc.org/specification) is a standardized Remote Procedure Call (RPC) protocol that is transport-agnostic,
and can be implemented over HTTP, WebSockets, or any other suitable network transport.
Rolo makes it easy to build HTTP-based protocol servers like this.
It provides flexible abstractions, so you can focus on the application code, while not making assumptions about the type of application your building.
Flask or FastAPI for instance make very strong assumptions that you are building REST/API-based web applications.
Other more low-level frameworks like Werkzeug are great, but will involve a lot of wheel re-inventing.

To keep the tutorial simple and focus on the primary aspects of rolo, we will build
* A simple JSON-RPC request parser
* A dispatcher system for single RPC requests
* Error handling middleware
* Result serialization

We only need the [handler chain](../handler_chain.md) and [gateway](../gateway.md) concepts to achieve this.

## Basic parser

Let's create super simple parser and encapsulate it into a handler:

```python
import dataclasses
import logging
from rolo import Response
from rolo.gateway import HandlerChain, RequestContext

LOG = logging.getLogger(__name__)


@dataclasses.dataclass
class RpcRequest:
    jsonrpc: str
    method: str
    id: str | int | None
    params: dict | list | None = None


def parse_request(chain: HandlerChain, context: RequestContext, response: Response):
    context.rpc_request_id = None

    doc = context.request.get_json()
    context.rpc_request_id = doc["id"]
    context.rpc_request = RpcRequest(
        doc["jsonrpc"],
        doc["method"],
        doc["id"],
        doc.get("params"),
    )
```

The handler simply parses the request body as JSON.
This is easy since the Werkzeug `Request` object
already [supports this](https://werkzeug.palletsprojects.com/en/latest/wrappers/#werkzeug.wrappers.Request.get_json).
We initialize the request context with an empty request ID, since that is later often referred back to.
It then creates a `RpcRequest` object that is attached to the `RequestContext` and can be used later in the chain.

Let's also create a handler to log the request if there is one.

```python
def log_request(chain: HandlerChain, context: RequestContext, response: Response):
    if context.rpc_request:
        LOG.info("RPC request object: %s", context.rpc_request)
```

We can now serve this through a Werkzeug dev server like this:

```python
from werkzeug.serving import run_simple

from rolo.gateway import Gateway
from rolo.gateway.wsgi import WsgiGateway


def main():
    logging.basicConfig(level=logging.DEBUG)

    gateway = Gateway(
        request_handlers=[
            parse_request,
            log_request,
        ],
    )

    run_simple("localhost", 8000, WsgiGateway(gateway))


if __name__ == "__main__":
    main()
```

When we run this, we can test it by sending a valid JSON-RPC request object to the server using `curl`:

```sh
curl -H "Content-Type: application/json" localhost:8000 \
  -d '{"jsonrpc": "2.0", "method": "subtract", "params": [42, 23], "id": 1}'
```

This should return nothing, but in the logs we should see:

```
INFO:__main__:RPC request object: RpcRequest(jsonrpc='2.0', method='subtract', id=1, params=[42, 23])
INFO:werkzeug:127.0.0.1 - - [20/Jul/2024 01:37:27] "POST / HTTP/1.1" 200 -
```

## Error handling

Let's add some basic error handling with exception handlers.

### Custom exceptions

JSON-RPC has pre-defined error codes, so it's useful to define those as python exceptions:

```python
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

# ... consider the remaining from https://www.jsonrpc.org/specification#error_object
```

### Raise exception in handler

Let's update the request parser to actually raise the `ParseError` we just created:

```python
def parse_request(chain: HandlerChain, context: RequestContext, response: Response):
    context.rpc_request_id = None

    try:
        doc = context.request.get_json()
    except werkzeug.exceptions.BadRequest as e:
        # werkzeug raises this exception if the json body is not valid
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
        raise InvalidRequest() from e
```

Now we need exception handlers that do something when these exceptions are raised in the handler chain.

### Generic exception logging

We can build a very generic exception logger which will be helpful for debugging:

```python
def log_exception(
    chain: HandlerChain,
    exception: Exception,
    context: RequestContext,
    response: Response,
):
    LOG.error("Exception in handler chain", exc_info=exception)
```

### RPC error serializer

Our RPC server should serialize specific `RpcError` instances that handlers raise into the appropriate objects.

```python
def serialize_rpc_error(
    chain: HandlerChain,
    exception: Exception,
    context: RequestContext,
    response: Response,
):
    if not isinstance(exception, RpcError):
        # we only run this handler when the exception is an RpcError
        return

    response.set_json(
        {
            "jsonrpc": "2.0",
            "error": {"code": exception.code, "message": exception.message},
            "id": context.rpc_request_id,
        }
    )
```

### Adding exception handlers

Now we can update the Gateway to also pass a list of handlers via `exception_handler`:

```python
    gateway = Gateway(
    request_handlers=[
        parse_request,
        log_request,
        locate_method,
    ],
    exception_handlers=[
        log_exception,
        serialize_rpc_error,
    ],
)
```

When we restart the server and pass a nonsense request, we should now see something like:

```console
curl -H "Content-Type: application/json" localhost:8000 -d 'foo'
```

```json
{"jsonrpc": "2.0", "error": {"code": -32700, "message": "Parse error"}, "id": null}
```

## Dispatching

Now we need a system to dispatch the RPC request to an actual Python implementation.
The dispatching system needs a _registry_ that maps method names to callable objects, and a _dispatcher_ that actually
invokes the method.
We'll separate these two concerns, since that will make it easier to add more middleware later.

### Registry

The registry holds a dictionary of methods, and simply attaches the found method to the context.
We'll come back to error handling later.

```python

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
```

We can now instantiate the Registry with a simple method that subtracts two numbers, and add it to the gateway.

```python
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
        ],
        # ...
    )

```

```{tip}
Assigning handlers names that are phrased as an imperative makes the high-level logic of the handler chain much easier to read.
```

Since we already added exception handling, when trying to invoke a non-existing method, we should already receive a correct error response:

```sh
curl -H "Content-Type: application/json" localhost:8000 \
  -d '{"jsonrpc": "2.0", "method": "foobar", "id": "1"}'
```
```json
{"jsonrpc": "2.0", "error": {"code": -32601, "message": "Method not found"}, "id": "1"}
```

### Dispatcher

The dispatcher takes the RPC request parameters and invokes the Python method.
This is fairly simple in Python, all we need to do is determine whether the parameters are a list or a dictionary, and unpack them into the method accordingly.
The result is then simply attached to the context, so we can later serialize it appropriately.

```python
def dispatch(chain: HandlerChain, context: RequestContext, response: Response):
    if not context.rpc_request_id:
        # this is a notification, so we don't want to dispatch anything
        return

    request: RpcRequest = context.rpc_request

    if isinstance(request.params, list):
        args = context.rpc_request.params
        kwargs = {}
    elif isinstance(request.params, dict):
        args = []
        kwargs = context.rpc_request.params
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
```

We can now add `dispatch` to the list of request handlers after `locate_method`.

### Serialize result

A very naive serialization could look like this:

```python
import json

def serialize_result(chain: HandlerChain, context: RequestContext, response: Response):
    if not context.result:
        return

    response.set_json(
        {
            "jsonrpc": "2.0",
            "result": json.dumps(context.result),
            "id": context.rpc_request_id,
        }
    )
```

We're assuming that the result invocation is json serializable for now.
This also shows the power of handler encapsulation: we can add error handling complexity for serialization later, while keeping the dispatcher simple.

Add `serialize_result` to the request handler chain, restart the server, and call the HTTP endpoint again:

```sh
curl -H "Content-Type: application/json" localhost:8000 \
  -d '{"jsonrpc": "2.0", "method": "subtract", "params": [42, 23], "id": 1}'
```

Which should now yield:
```json
{"jsonrpc": "2.0", "result": "19", "id": "1"}
```

## Complete program

Here is the complete program we have so far:

```python
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
```

## Things left to do

There are plenty of JSON-RPC features still missing that you can implement yourself to learn more about rolo:

* Error data: The [error object](https://www.jsonrpc.org/specification#error_object) also defines a `data` field that can contain additional information about the exception.
* Input parameter validation: a handler to match using Python reflection the arguments of the method to the params of the RPC request, and raise exceptions accordingly.
* Serialization error handling: Methods may return arbitrary objects which may not be JSON serializable. We'd want either more robust JSON serialization or better error handling.
* Batch: The client may send multiple RpcRequest objects in one request as list, called a [Batch](https://www.jsonrpc.org/specification#batch)
* Authorization: Bearer-token authorization can be trivial to implement using a handler and checking the Authorization header

## Conclusion

We implemented a good chunk of a fully functional JSON-RPC over HTTP server using the rolo framework.
It is an example that showcases the strengths of rolo over other web frameworks for this type of application.
Rolo is not _just_ designed for the 90% web app use cases like Flask or FastAPI, but flexible enough to implement a wide range of use cases, including protocol servers or proxy servers,
all while providing the same old tools you are used to, like the `Request` object.

The handler chain makes it easy to de-compose complex server behavior into smaller components (handlers) that can evolve independently.
Handlers can be written both in functional style, or OOP style, depending on your needs.
They can have state, making it easy to integrate databases or other state mechanisms.

Combining handlers into a chain, can make it very easy to understand on a high-level what the application does.
Let's review the final Gateway again:

```python
gateway = Gateway(
    request_handlers=[
        parse_request,
        log_request,
        locate_method,
        dispatch,
        serialize_result,
    ],
    exception_handlers=[
        log_exception,
        serialize_rpc_error,
    ],
)
```

Just from looking at this piece of code, you can understand immediately the flow of the server.
Compare this to other applications, where you have a very deep call stack, and need to trace the flow through the stack.
This structure also makes it very easy to extend.
Simply add a handler as middleware into the handler chain.
For example, you could easily add a finalizer to log the result, or an authorization handler at the beginning of the call chain that terminates the chain on unauthorized requests.

In summary, rolo is a flexible framework that goes beyond traditional web applications, all while providing you familiar concepts.
It's designed for modularity and maintainability, to build server applications that are easy to extend and to maintain by multiple developers.
