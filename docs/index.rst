Rolo documentation
==================

Rolo is a flexible framework and library to build HTTP-based server applications beyond microservices and REST APIs.
You can build HTTP-based RPC servers, websocket proxies, or other server types that typical web frameworks are not designed for.
Rolo was originally designed to build the AWS RPC protocol server in `LocalStack <https://github.com/localstack/localstack>`_.

Rolo extends `Werkzeug <https://github.com/pallets/werkzeug/>`_, a flexible Python HTTP server library, for you to use concepts you are familiar with like ``@route``, ``Request``, or ``Response``.
It introduces the concept of a ``Gateway`` and ``HandlerChain``, an implementation variant of the `chain-of-responsibility pattern <https://en.wikipedia.org/wiki/Chain-of-responsibility_pattern>`_.

Rolo is designed for environments that do not use asyncio, but still require asynchronous HTTP features like HTTP2 SSE or Websockets.
To allow asynchronous communication, Rolo introduces an ASGI/WSGI bridge, that allows you to serve Rolo applications through ASGI servers like Hypercorn.


.. toctree::
   :maxdepth: 2
   :caption: Contents:

Quickstart
----------

.. toctree::
   :maxdepth: 2

   getting_started


User Guide
----------

.. toctree::
   :maxdepth: 2

   router
   handler_chain
   gateway
   websockets
   serving
