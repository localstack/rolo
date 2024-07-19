Serving
=======

This guide shows you how to serve Rolo components through different Python web server technologies.

WSGI
----

Serving a Router as WSGI app
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

If you only need a ``Router`` instance to serve your application, you can convert to a WSGI app using the ``Router.wsgi()`` method.

.. code-block:: python

    from rolo import Router, route
    from rolo.dispatcher import handler_dispatcher

    @route("/")
    def index(request):
        return "hello world"

    router = Router(dispatcher=handler_dispatcher())
    router.add(index)

    app = router.wsgi()


Now you can use any old WSGI compliant server to serve the application.
For example, if this file is stored in ``myapp.py``, using gunicorn, you can:

.. code-block:: sh

    pip install gunicorn
    gunicorn -w 4 myapp:app


Serving a Gateway as WSGI app
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Unless you need Websockets, the Rolo Request object is fully WSGI compliant, so you can also use any WSGI server to serve a ``Gateway``.
Simply use the ``WSGIGateway`` adapter.

.. code-block:: python

    from rolo.gateway import Gateway
    from rolo.gateway.wsgi import WsgiGateway

    gateway: Gateway = ...

    app = WsgiGateway(gateway)

Similar to the previous example, you can serve the ``app`` object through any WSGI compliant server.

ASGI
----

ASGI servers like Hypercorn allow asynchronous server communication, which is needed for HTTP/2 streaming or Websockets.
Gateways can be served through the ``AsgiGateway`` adapter, which exposes a ``Gateway`` as an ASGI3 application.
Under the hood, it uses our own ASGI/WSGI bridge (``AsgiAdapter``), and converts ASGI calls to WSGI calls for regular HTTP requests, and uses ASGI websockets for serving rolo websockets.
File ``myapp.py``:

.. code-block:: python

    from rolo.gateway import Gateway
    from rolo.gateway.asgi import AsgiGateway

    gateway: Gateway = ...

    app = AsgiGateway(gateway)

Now you can use Hypercorn or other ASGI servers to serve the ``app`` object.

.. code-block:: sh

    pip install hypercorn
    hypercorn myapp:app

Twisted
-------

Rolo can be served through `Twisted <https://twisted.org/>`_, which supports both WSGI and Websockets.
You will need twisted, and wsproto installed ``pip install twisted wsproto``.

.. code-block:: python

    from rolo.gateway import Gateway
    from rolo.serving.twisted import TwistedGateway
    from twisted.internet import endpoints, reactor

    gateway: Gateway = ...

    # Rolo/Twisted adapter, that exposes a Rolo Gateway as a twisted.web.server.Site object
    site = TwistedGateway(gateway)

    endpoint = endpoints.TCP4ServerEndpoint(reactor, 8000)
    endpoint.listen(site)

    reactor.run()
