<p align="center">
  <img src="https://github.com/thrau/rolo/assets/3996682/268786a8-6335-412f-bc72-8080f97cbb5a" alt="Rolo HTTP">
</p>
<p align="center">
  Rolo HTTP: A Python framework for building HTTP-based server applications.
</p>

# Rolo HTTP

Rolo is a flexible framework and library to build HTTP-based server applications beyond microservices and REST APIs.
You can build HTTP-based RPC servers, websocket proxies, or other server types that typical web frameworks are not designed for.

Rolo extends [Werkzeug](https://github.com/pallets/werkzeug/), a flexible Python HTTP server library, for you to use concepts you are familiar with like `Router`, `Request`, `Response`, or `@route`.
It introduces the concept of a `Gateawy` and `HandlerChain`, an implementation variant of the [chain-of-responsibility pattern](https://en.wikipedia.org/wiki/Chain-of-responsibility_pattern).

Rolo is designed for environments that do not use asyncio, but still require asynchronous HTTP features like HTTP2 SSE or Websockets.
To allow asynchronous communication, Rolo introduces an ASGI/WSGI bridge, that allows you to serve Rolo applications through ASGI servers like Hypercorn.

## Usage

### Default router example

```python
from rolo import Router
from werkzeug import Request
from werkzeug.serving import run_simple

@route("/users")
def user(_: Request, args):
    assert not args
    return Response("user")

@route("/users/<int:user_id>")
def user_id(_: Request, args):
    assert args
    return Response(f"{args['user_id']}")

router = Router()
router.add(user)
router.add(user_id)

# convert Router to a WSGI app and serve it through werkzeug
app = Request.application(router.dispatch)
run_simple('localhost', 8080, app, use_reloader=True)
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
