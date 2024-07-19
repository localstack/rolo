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

Read more in the [serving](serving.md#serving) section.
