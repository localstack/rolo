Gateway
=======

Builtin Handlers
----------------

Router Handler
~~~~~~~~~~~~~~

Sometimes you have a ``Gateway`` but also want to use the router.
You can use the ``RouterHandler`` adapter to make a ``Router`` look like a handler chain ``Handler``, and then pass it as handler to a Gateway.

.. code-block:: python

    from rolo import Gateway, Router
    from rolo.gateway.handlers import RouterHandler

    router: Router = ...
    gateway: Gateway = ...

    gateway.request_handlers.append(RouterHandler(router))
