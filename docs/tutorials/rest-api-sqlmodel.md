# Tutorial: REST API with SQLModel

In this tutorial, we will explore how rolo can be used to build RESTful API servers with a database backend, using concepts you are familiar with, such as from Flask or FastAPI, and adding middleware using the [handler chain](../handler_chain.md).

## Introduction

A bread-and-butter use case of web frameworks is implementing [resources](https://restful-api-design.readthedocs.io/en/latest/resources.html) using RESTful API design.
Mapping web API concepts (like a `Request` object) to an internal resource model (like a Simple `Hero` API [described in the SQLModel docs](https://sqlmodel.tiangolo.com/tutorial/fastapi/simple-hero-api/)).
 

## Defining the SQLModel

Here's a simple `SQLModel` class that will map to the Hero table in the database.
SQLModel uses SQLAlchemy to map pydantic classes to tables.

```python
from typing import Optional

from sqlmodel import Field, SQLModel

class Hero(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str
    secret_name: str
    age: Optional[int] = None
```

## Defining the REST API

Now let's define the basic Create, Read, List, Delete API.
Each HTTP method will map to one of these operations.
Rolo allows you to declare the route's signatures using pydantic BaseModel types.
This means, adding the attribute `hero: Hero` into your route signature tells rolo that this method accepts `application/json` payloads that are serialized into the `Hero` class using pydantic.
Since `SQLModel` is also a `pydantic.BaseModel`, we can use our `Hero` object directly.

```python
from rolo import Request, route

class HeroResource:

    @route("/heroes", methods=["GET"])
    def list_heroes(self, request: Request, hero_id: int) -> list[Hero]:
        return

    @route("/heroes/<int:hero_id>", methods=["GET"])
    def get_hero(self, request: Request, hero_id: int) -> Hero:
        return

    @route("/heroes", methods=["POST"])
    def add_hero(self, request: Request, hero: Hero) -> Hero:
        return

    @route("/heroes/<int:hero_id>", methods=["DELETE"])
    def delete_hero(self, request: Request, hero_id: int):
        return

```

## Using SQLModel with rolo

We pass to the `HeroResource` the sqlalchemy `Engine` object, that will allow us to perform database operations.
We will later inject it as a dependency when creating the `HeroResource`.

```python
from sqlalchemy.engine import Engine

class HeroResource:
    db_engine: Engine

    def __init__(self, db_engine: Engine):
        self.db_engine = db_engine

    ...
```

Let's look at the full implementation of our resource.
Every method now uses the appropriate SQLAlchemy database operations.
You can see that database objects are serialized and deserialized automatically.

```python
from typing import Optional

from sqlalchemy.engine import Engine
from sqlmodel import Field, SQLModel, Session, select, delete

from rolo import Request, Response, route


class Hero(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str
    secret_name: str
    age: Optional[int] = None

    

class HeroResource:
    db_engine: Engine

    def __init__(self, db_engine: Engine):
        self.db_engine = db_engine

    @route("/heroes", methods=["GET"])
    def list_heroes(self, request: Request) -> list[Hero]:
        with Session(self.db_engine) as session:
            statement = select(Hero)
            results = session.exec(statement)
            return list(results)

    @route("/heroes/<int:hero_id>", methods=["GET"])
    def get_hero(self, request: Request, hero_id: int) -> Hero | Response:
        with Session(self.db_engine) as session:
            statement = select(Hero).where(Hero.id == hero_id)
            results = session.exec(statement)
            if hero := results.first():
                return hero
        return Response.for_json({"message": "not found"}, status=404)

    @route("/heroes", methods=["POST"])
    def add_hero(self, request: Request, hero: Hero) -> Hero:
        with Session(self.db_engine) as session:
            session.add(hero)
            session.commit()
            session.refresh(hero)
        return hero

    @route("/heroes/<int:hero_id>", methods=["DELETE"])
    def delete_hero(self, request: Request, hero_id: int) -> None:
        with Session(self.db_engine) as session:
            statement = delete(Hero).where(Hero.id == hero_id)
            session.exec(statement)
            session.commit()

```

For example, this CURL call will produce the following result:

```bash
curl -X POST
  -H 'Content-Type: application/json' \
  -d '{"name": "Superman", "secret_name": "Clark Kent", "age": 150}' \
  http://localhost:8000/heroes
```
```json
{"name": "Superman", "id": 1, "secret_name": "Clark Kent", "age": 150}
```

## Add simple authorization middleware

Next, we're going to add a simple authorization middleware that uses the Bearer token [HTTP authentication scheme](https://developer.mozilla.org/en-US/docs/Web/HTTP/Authentication).
The basic idea is that there is an authorization database, which holds a set of valid auth tokens.
The client sends the auth token through the `Authorization: Bearer <token>` header.
For every request, we want to check whether the header is present and check the token against the database.
If not, then we want to respond with a `401 Unauthorized` error.
To that end, we will introduce a [handler chain](../handler_chain.md) handler.

### Authorization handler

Here is the example handler code.
Notice how you can use the [`authorization`](https://werkzeug.palletsprojects.com/en/2.3.x/wrappers/#werkzeug.wrappers.Request.authorization) attribute of the werkzeug request object, to access the header directly.
You are working with the [`Authorization`](https://werkzeug.palletsprojects.com/en/2.3.x/datastructures/#werkzeug.datastructures.Authorization) data structure.
Next, you can raise werkzeug `Unauthorized` exceptions, which we will then handle with the builtin `WerkzeugExceptionHandler`.

```python
from werkzeug.exceptions import Unauthorized

from rolo import Response
from rolo.gateway import HandlerChain, RequestContext


class AuthorizationHandler:
    authorized_tokens: set[str]
    """Set of tokens that can be used for authentication."""

    def __init__(self, authorized_tokens: set[str]):
        self.authorized_tokens = authorized_tokens

    def __call__(self, chain: HandlerChain, context: RequestContext, response: Response):
        auth = context.request.authorization

        if not auth:
            raise Unauthorized("No authorization header")
        if not auth.type == "bearer":
            raise Unauthorized("Unknown authorization type %s" % auth.type)
        if auth.token not in self.authorized_tokens:
            raise Unauthorized("Invalid token")
```

### Handler chain

Let's put together an appropriate handler chain using both our `AuthorizationHandler`, and the builtin handlers `RouterHandler` and `WerkzeugExceptionHandler`,
as well as all SQLModel resources we need.

First, we create our `HeroResource` and inject the SQLAlchemy database engine into it.
Then, we create a rolo `Router` with a handler dispatcher, which takes care of invoking our routes correctly,
and add the resource.
The HTTP paths are scanned from the `@route` decorators automatically by the router.
Then, we instantiate our Gateway and add our handlers.

The first handler is the authorization handler we create, which should always be executed first.
In this example, the authorization handler is instantiated with a static set of tokens, in this case simply `mysecret`.
In a production system, these would come from a secrets database or some other backend, but it illustrates the idea.

Then we attach a `RouterHandler`, which allows us to serve a `Router` through the handler chain.
Finally, we add the default `WerkzeugExceptionHandler`, which automatically handles exceptions like `NotFound`.


```python
import typing as t

from sqlalchemy import create_engine
from sqlmodel import SQLModel
from werkzeug.exceptions import Unauthorized

from rolo import Router
from rolo.dispatcher import handler_dispatcher
from rolo.gateway import Gateway, HandlerChain, RequestContext
from rolo.gateway.handlers import RouterHandler, WerkzeugExceptionHandler

def main():
    # create database engine and create tables
    engine = create_engine("sqlite:///database.db")
    SQLModel.metadata.create_all(engine)

    # create router with resource
    router = Router(handler_dispatcher())
    router.add(HeroResource(engine))

    # gateway
    gateway = Gateway(
        request_handlers=[
            AuthorizationHandler({"mysecret"}),
            RouterHandler(router, respond_not_found=True),
        ],
        exception_handlers=[
            WerkzeugExceptionHandler(output_format="json"),
        ]
    )
```

The created `Gateway` instance can now be served through a WSGI server like the Werkzeug developer server.
To that end, we wrap the `gateway` in a rolo `WsgiGateway` adapter, which exposes the `Gateway` as a WSGI application.

```python
from werkzeug import run_simple

from rolo.gateway.wsgi import WsgiGateway

def main():
    wsgi = WsgiGateway(gateway)
    run_simple("localhost", 8000, wsgi)
```

## Complete program

Here's the complete program:

```python
import typing as t

from sqlalchemy import create_engine, Engine
from werkzeug import run_simple
from werkzeug.exceptions import Unauthorized

from rolo import Router, Request, Response, route
from rolo.dispatcher import handler_dispatcher
from rolo.gateway import Gateway, HandlerChain, RequestContext
from rolo.gateway.handlers import RouterHandler, WerkzeugExceptionHandler
from rolo.gateway.wsgi import WsgiGateway

if t.TYPE_CHECKING:
    pass

from typing import Optional

from sqlmodel import Field, Session, SQLModel, select, delete


class Hero(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str
    secret_name: str
    age: Optional[int] = None


class HeroResource:
    db_engine: Engine

    def __init__(self, db_engine: Engine):
        self.db_engine = db_engine

    @route("/heroes", methods=["GET"])
    def list_heroes(self, request: Request) -> list[Hero]:
        with Session(self.db_engine) as session:
            statement = select(Hero)
            results = session.exec(statement)
            return list(results)

    @route("/heroes/<int:hero_id>", methods=["GET"])
    def get_hero(self, request: Request, hero_id: int) -> Hero | Response:
        with Session(self.db_engine) as session:
            statement = select(Hero).where(Hero.id == hero_id)
            results = session.exec(statement)
            if hero := results.first():
                return hero
        return Response.for_json({"message": "not found"}, status=404)

    @route("/heroes", methods=["POST"])
    def add_hero(self, request: Request, hero: Hero) -> Hero:
        with Session(self.db_engine) as session:
            session.add(hero)
            session.commit()
            session.refresh(hero)
        return hero

    @route("/heroes/<int:hero_id>", methods=["DELETE"])
    def delete_hero(self, request: Request, hero_id: int) -> None:
        with Session(self.db_engine) as session:
            statement = delete(Hero).where(Hero.id == hero_id)
            session.exec(statement)
            session.commit()


class AuthorizationHandler:
    authorized_tokens: set[str]

    def __init__(self, authorized_tokens: set[str]):
        self.authorized_tokens = authorized_tokens

    def __call__(self, chain: HandlerChain, context: RequestContext, response: Response):
        auth = context.request.authorization

        if not auth:
            raise Unauthorized("No authorization header")
        if not auth.type == "bearer":
            raise Unauthorized("Unknown authorization type %s" % auth.type)
        if auth.token not in self.authorized_tokens:
            raise Unauthorized("Invalid token")


def wsgi():
    # create engine
    engine = create_engine("sqlite:///database.db")
    SQLModel.metadata.create_all(engine)

    # create router with resource
    router = Router(handler_dispatcher())
    router.add(HeroResource(engine))

    # gateway
    gateway = Gateway(
        request_handlers=[
            AuthorizationHandler({"mysecret"}),
            RouterHandler(router, respond_not_found=True),
        ],
        exception_handlers=[
            WerkzeugExceptionHandler(output_format="json"),
        ]
    )

    return WsgiGateway(gateway)


def main():
    run_simple("localhost", 8000, wsgi())


if __name__ == '__main__':
    main()
```

Running this program will output something like:

```console
WARNING: This is a development server. Do not use it in a production deployment. Use a production WSGI server instead.
 * Running on http://localhost:8000
Press CTRL+C to quit
```

You can also look in the `examples/rest-api-sqlmodel` directory for a more modularized version of the app.

## Conclusion

The example shows how Rolo allows you to combine classic flask or FastAPI-styled routers, with an object-relational
mapper through its pydantic integration, and serve it with custom middleware through Rolo's handler chain concept.

Handler chains make it easy to write custom middleware like the authorization handler, or exception handlers, and layer
them around your application logic.
The pydantic integration allows you to write your resources in an object-oriented style, and abstracts away most
serialization logic.

If you want to learn more about how to compose more complex logic in a handler chain, check out our
[tutorial on building a JSON RPC Server](./jsonrpc-server.md).
