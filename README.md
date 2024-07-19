<p align="center">
  <img src="https://github.com/thrau/rolo/assets/3996682/268786a8-6335-412f-bc72-8080f97cbb5a" alt="Rolo HTTP">
</p>
<p align="center">
  Rolo HTTP: A Python framework for building HTTP-based server applications.
</p>

# Rolo HTTP

<p>
  <a href="https://github.com/localstack/rolo/actions/workflows/build.yml"><img alt="CI badge" src="https://github.com/localstack/rolo/actions/workflows/build.yml/badge.svg"></img></a>
  <a href="https://pypi.org/project/rolo/"><img alt="PyPI Version" src="https://img.shields.io/pypi/v/rolo?color=blue"></a>
  <a href="https://coveralls.io/github/localstack/rolo?branch=main"><img src="https://coveralls.io/repos/github/localstack/rolo/badge.svg?branch=main"></a>
  <a href="https://img.shields.io/pypi/l/rolo.svg"><img alt="PyPI License" src="https://img.shields.io/pypi/l/rolo.svg"></a>
  <a href="https://github.com/psf/black"><img alt="Code style: black" src="https://img.shields.io/badge/code%20style-black-000000.svg"></a>
</p>

Rolo is a flexible framework and library to build HTTP-based server applications beyond microservices and REST APIs.
You can build HTTP-based RPC servers, websocket proxies, or other server types that typical web frameworks are not designed for.

Rolo extends [Werkzeug](https://github.com/pallets/werkzeug/), a flexible Python HTTP server library, for you to use concepts you are familiar with like `Router`, `Request`, `Response`, or `@route`.
It introduces the concept of a `Gateway` and `HandlerChain`, an implementation variant of the [chain-of-responsibility pattern](https://en.wikipedia.org/wiki/Chain-of-responsibility_pattern).

Rolo is designed for environments that do not use asyncio, but still require asynchronous HTTP features like HTTP2 SSE or Websockets.
To allow asynchronous communication, Rolo introduces an ASGI/WSGI bridge, that allows you to serve Rolo applications through ASGI servers like Hypercorn.

## Usage

### Default router example

Routers are based on Werkzeug's [URL Map](https://werkzeug.palletsprojects.com/en/2.3.x/routing/), but dispatch to handler functions directly.
The `@route` decorator works similar to Flask or FastAPI, but they are not tied to an Application object.
Instead, you can define routes on functions or methods, and then add them directly to the router.

```python
from rolo import Router, route, Response
from werkzeug import Request
from werkzeug.serving import run_simple

@route("/users")
def user(_request: Request, args):
    assert not args
    return Response("user")

@route("/users/<int:user_id>")
def user_id(_request: Request, args):
    assert args
    return Response(f"{args['user_id']}")

router = Router()
router.add(user)
router.add(user_id)

# convert Router to a WSGI app and serve it through werkzeug
run_simple('localhost', 8080, router.wsgi(), use_reloader=True)
```

### Pydantic integration

Routers use dispatchers to dispatch the request to functions.
In the previous example, the default dispatcher calls the function with the `Request` object and the request arguments as dictionary.
The "handler dispatcher" can transform functions into more Flask or FastAPI-like functions, that also allow you to integrate with Pydantic.
Here's how the default example from the FastAPI documentation would look like with rolo:

```python
import pydantic
from werkzeug import Request
from werkzeug.serving import run_simple

from rolo import Router, route


class Item(pydantic.BaseModel):
    name: str
    price: float
    is_offer: bool | None = None


@route("/", methods=["GET"])
def read_root(request: Request):
    return {"Hello": "World"}


@route("/items/<int:item_id>", methods=["GET"])
def read_item(request: Request, item_id: int):
    return {"item_id": item_id, "q": request.query_string}


@route("/items/<int:item_id>", methods=["PUT"])
def update_item(request: Request, item_id: int, item: Item):
    return {"item_name": item.name, "item_id": item_id}


router = Router()
router.add(read_root)
router.add(read_item)
router.add(update_item)

# convert Router to a WSGI app and serve it through werkzeug
run_simple("localhost", 8080, router.wsgi(), use_reloader=True)
```

### Gateway & Handler Chain

A rolo `Gateway` holds a set of request, response, and exception handlers, as well as request finalizers.
Gateway instances can then be served as WSGI or ASGI applications by using the appropriate serving adapter.
Here is a simple example of a Gateway with just one handler that returns the URL and method that was invoked.

```python
from werkzeug import run_simple

from rolo import Response
from rolo.gateway import Gateway, HandlerChain, RequestContext
from rolo.gateway.wsgi import WsgiGateway


def echo_handler(chain: HandlerChain, context: RequestContext, response: Response):
    response.status_code = 200
    response.set_json({"url": context.request.url, "method": context.request.method})


gateway = Gateway(request_handlers=[echo_handler])

app = WsgiGateway(gateway)
run_simple("localhost", 8080, app, use_reloader=True)
```

Serving this will yield:

```console
curl http://localhost:8080/hello-world
{"url": "http://localhost:8080/hello-world", "method": "GET"}
```


## Develop

### Quickstart

to install the python and other developer requirements into a venv run:

    make install

### Format code

We use black and isort as code style tools.
To execute them, run:

    make format

### Build distribution

To build a wheel and source distribution, simply run

    make dist
