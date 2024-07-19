Rolo documentation
==================

<p align="center">
  <img src="https://github.com/thrau/rolo/assets/3996682/268786a8-6335-412f-bc72-8080f97cbb5a" alt="Rolo HTTP">
</p>
<p align="center">
  <b>Rolo HTTP: A Python framework for building HTTP-based server applications.</b>
</p>

## Introduction

Rolo is a flexible framework and library to build HTTP-based server applications beyond microservices and REST APIs.
You can build HTTP-based RPC servers, websocket proxies, or other server types that typical web frameworks are not designed for.
Rolo was originally designed to build the AWS RPC protocol server in [LocalStack](https://github.com/localstack/localstack).

Rolo extends [Werkzeug](https://github.com/pallets/werkzeug/), a flexible Python HTTP server library, for you to use concepts you are familiar with like ``@route``, ``Request``, or ``Response``.
It introduces the concept of a ``Gateway`` and ``HandlerChain``, an implementation variant of the [chain-of-responsibility pattern](https://en.wikipedia.org/wiki/Chain-of-responsibility_pattern).

Rolo is designed for environments that do not use asyncio, but still require asynchronous HTTP features like HTTP2 SSE or Websockets.
To allow asynchronous communication, Rolo introduces an ASGI/WSGI bridge, that allows you to serve Rolo applications through ASGI servers like Hypercorn.

## Table of Content

```{toctree}
:caption: Quickstart
:maxdepth: 2

getting_started
```

```{toctree}
:caption: User Guide
:maxdepth: 2

router
handler_chain
gateway
websockets
serving
```

