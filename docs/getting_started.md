Getting started
===============

## Installation

Rolo is hosted on [pypi](https://pypi.org/project/rolo/) and can be installed via pip.

```sh
pip install rolo
```

## Hello World

Rolo provides different ways of building a web application.
It provides familiar concepts such as Router and `@route`, but also more flexible concepts like a Handler Chain.

### Router

Here is a simple [`Router`](router.md) that can be served as WSGI application using the Werkzeug dev server.
If you are familiar with Flask, `@route` works in a similar way.

```python
from werkzeug import Request
from werkzeug.serving import run_simple

from rolo import Router, route
from rolo.dispatcher import handler_dispatcher

@route("/")
def hello(request: Request):
    return {"message": "Hello World"}

router = Router(dispatcher=handler_dispatcher())
router.add(hello)

run_simple("localhost", 8000, router.wsgi())
```

And to test:
```console
curl localhost:8000/
```
Should yield
```json
{"message": "Hello World"}
```

`rolo.Request` and `rolo.Response` objects work in the same way as Werkzeug's [Request / Response](https://werkzeug.palletsprojects.com/en/latest/wrappers/) wrappers.

### Gateway

A Gateway holds a set of handlers that are combined into a handler chain.
Here is a simple example with a single request handler that dynamically creates a response object similar to httpbin.

```python
from werkzeug.serving import run_simple

from rolo import Response
from rolo.gateway import Gateway, RequestContext, HandlerChain
from rolo.gateway.wsgi import WsgiGateway


def echo_handler(chain: HandlerChain, context: RequestContext, response: Response):
    response.status_code = 200
    response.set_json(
        {
            "method": context.request.method,
            "path": context.request.path,
            "query": context.request.args,
            "headers": dict(context.request.headers),
        }
    )
    chain.stop()


gateway = Gateway(
    request_handlers=[echo_handler],
)

run_simple("localhost", 8000, WsgiGateway(gateway))
```

And to test:
```console
curl -s -X POST "localhost:8000/foo/bar?a=1&b=2" | jq .
```
Should give you:
```json
{
  "method": "POST",
  "path": "/foo/bar",
  "query": {
    "a": "1",
    "b": "2"
  },
  "headers": {
    "Host": "localhost:8000",
    "User-Agent": "curl/7.81.0",
    "Accept": "*/*"
  }
}
```

## Next Steps

Learn how to
* Use the [Router](router.md)
* Use the [Handler Chain](handler_chain.md)
* [Serve](serving.md) rolo through your favorite web server
