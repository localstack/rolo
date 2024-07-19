Handler Chain
=============

The rolo handler chain implements a variant of the chain-of-responsibility pattern to process an incoming HTTP request.
It is meant to be used together with a [`Gateway`](gateway.md), which is responsible for creating `HandlerChain` instances.

Handler chains are a powerful abstraction to create complex HTTP server behavior, while keeping code cleanly encapsulated and the high-level logic easy to understand.
You can find a simple example how to create a handler chain in the [Getting Started](getting_started.md) guide.

## Behavior

A handler chain consists of:
* request handlers: process the request and attempt to create an initial response
* response handlers: process the response
* finalizers: handlers that are always executed at the end of running a handler chain
* exception handlers: run when an exception occurs during the execution of a handler

Each HTTP request coming into the server has its own `HandlerChain` instance, since the handler chain holds state for the handling of a request.
A handler chain can be in three states that can be controlled by the handlers.

* Running - the implicit state in which _all_ handlers are executed sequentially
* Stopped - a handler has called `chain.stop()`. This stops the execution of all request handlers, and
  proceeds immediately to executing the response handlers. Response handlers and finalizers will be run,
  even if the chain has been stopped.
* Terminated - a handler has called `chain.terminate()`. This stops the execution of all request
  handlers, and all response handlers, but runs the finalizers at the end.

If an exception occurs during the execution of request handlers, the chain by default stops the chain,
then runs each exception handler, and finally runs the response handlers.
Exceptions that happen during the execution of response or exception handlers are logged but do not modify the control flow of the chain.

## Handlers

Request handlers, response handlers, and finalizers need to satisfy the `Handler` protocol:

```python
from rolo import Response
from rolo.gateway import HandlerChain, RequestContext

def handle(chain: HandlerChain, context: RequestContext, response: Response):
    ...
```

* `chain`: the HandlerChain instance currently being executed. The handler implementation can call for example `chain.stop()` to indicate that it should skip all other request handlers.
* `context`: the RequestContext contains the rolo `Request` object, as well as a universal property store. You can simply call `context.myattr = ...` to pass a value down to the next handler
* `response`: Handlers of a handler chain don't return a response, instead the response being populated is handed down from handler to handler, and can thus be enriched

### Exception Handlers

Exception handlers are similar, only they are also passed the `Exception` that was raised in the handler chain.

```python
from rolo import Response
from rolo.gateway import HandlerChain, RequestContext

def handle(chain: HandlerChain, exception: Exception, context: RequestContext, response: Response):
    ...
```

## Builtin Handlers

### Router handler

Sometimes you have a `Gateway` but also want to use the [`Router`](router.md).
You can use the `RouterHandler` adapter to make a `Router` look like a handler chain `Handler`, and then pass it as handler to a Gateway.

```python
from rolo import Router
from rolo.gateway import Gateway
from rolo.gateway.handlers import RouterHandler

router: Router = ...
gateway: Gateway = ...

gateway.request_handlers.append(RouterHandler(router))
```

### Empty response handler

With the `EmptyResponseHandler` response handler automatically creates a default response if the response in the chain is empty.
By default, it creates an empty 404 response, but it can be customized:

```python
from rolo.gateway.handlers import EmptyResponseHandler

gateway.response_handlers.append(EmptyResponseHandler(status_code=404, body=b'404 Not Found'))
```

### Werkzeug exception handler

Werkzeug has a very useful [HTTP exception hierarchy](https://werkzeug.palletsprojects.com/en/latest/exceptions/) that can be used to programmatically trigger HTTP errors.
For instance, a request handler may raise a `NotFound` error.
To get the Gateway to automatically handle those exceptions and render them into JSON objects or HTML, you can use the `WerkzeugExceptionHandler`.

```python
from rolo.gateway.handlers import WerkzeugExceptionHandler

gateway.exception_handlers.append(WerkzeugExceptionHandler(output_format="json"))
```

In your request handler you can now raise any exception from `werkzeug.exceptions` and it will be rendered accordingly.
