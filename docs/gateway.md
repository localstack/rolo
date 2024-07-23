Gateway
=======

The `Gateway` serves as the factory for `HandlerChain` instances.
It also serves as the interface to HTTP servers.

## Creating a Gateway

```python
from rolo.gateway import Gateway

gateway = Gateway(
    request_handlers=[
        ...
    ],
    response_handlers=[
        ...
    ],
    exception_handlers=[
        ...
    ],
    finalizers=[
        ...
    ]
)
```

## Protocol adapters

You can use `rolo.gateway.wsgi` or `rolo.gateway.asgi` to expose a `Gateway` as either a WSGI or ASGI app.

Read more in the [serving](serving.md) section.

## Custom `RequestContext`

You can add a custom request context with type hints or your own methods by setting the `context_class` parameter in the constructor.
First, define a request context subclass:

```python
from rolo.gateway import RequestContext

class MyContext(RequestContext):
    myattr: str
```

Then, when you instantiate the Gateway:

```python
gateway = Gateway(
    request_handlers=[
        ...
    ],
    context_class=MyContext
)
```

In your handlers, you can now reference your context:

```python
def handler(chain: HandlerChain, context: MyContext, response: Response):
    ...
```
