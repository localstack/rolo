# Tutorial: REST API with SQLModel

In this tutorial, we will explore how rolo can be used to build REST API servers with concepts you are familiar with from Flask or FastAPI,
and adding middleware using the [handler chain](../handler_chain.md).

## Introduction

TODO

## Defining the SQLModel

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
    def add_hero(self, request: Request, hero: Hero):
        return
```

## Using SQLModel with rolo



```python
from sqlalchemy.engine import Engine

class HeroResource:
    db_engine: Engine

    def __init__(self, db_engine: Engine):
        self.db_engine = db_engine

    ...
```

```python
from typing import Optional

from sqlalchemy.engine import Engine
from sqlmodel import Field, SQLModel, Session, select

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
            return list(results.all())

    @route("/heroes/<int:hero_id>", methods=["GET"])
    def get_hero(self, request: Request, hero_id: int) -> Hero | Response:
        with Session(self.db_engine) as session:
            statement = select(Hero).where(Hero.id == hero_id)
            results = session.exec(statement)
            for hero in results:
                return hero
        return Response.for_json({"message": "not found"}, status=404)

    @route("/heroes", methods=["POST"])
    def add_hero(self, request: Request, hero: Hero) -> Hero:
        with Session(self.db_engine) as session:
            session.add(hero)
            session.commit()
            session.refresh(hero)
        return hero


```

## Add simple authorization middleware

Next, we're going to add a simple authorization middleware that uses the Bearer token [HTTP authentication scheme](https://developer.mozilla.org/en-US/docs/Web/HTTP/Authentication).
The basic idea is that there is an authorization database, which holds a set of valid auth tokens.
The clients sends the auth token through the `Authorization: Bearer <token>` header.
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
as well as all SQLModel resources we need:

```python
def main():
    # create database engine
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

TODO: breakdown


## Complete program

Here's the complete program:

```python
from typing import Optional

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlmodel import Field, Session, SQLModel, select
from werkzeug import run_simple
from werkzeug.exceptions import Unauthorized

from rolo import Request, Response, Router, route
from rolo.dispatcher import handler_dispatcher
from rolo.gateway import Gateway, HandlerChain, RequestContext
from rolo.gateway.handlers import RouterHandler, WerkzeugExceptionHandler
from rolo.gateway.wsgi import WsgiGateway


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
            for hero in results:
                return hero
        return Response.for_json({"message": "not found"}, status=404)

    @route("/heroes", methods=["POST"])
    def add_hero(self, request: Request, hero: Hero) -> Hero:
        with Session(self.db_engine) as session:
            session.add(hero)
            session.commit()
            session.refresh(hero)
        return hero


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


def main():
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

    run_simple("localhost", 8000, WsgiGateway(gateway))


if __name__ == '__main__':
    main()
```

## Conclusion

TODO
