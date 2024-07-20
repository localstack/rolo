
```python
from typing import Optional

from sqlmodel import Field, SQLModel

class Hero(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str
    secret_name: str
    age: Optional[int] = None
```

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

```python
from sqlalchemy import Engine

class HeroResource:
    db_engine: Engine

    def __init__(self, db_engine: Engine):
        self.db_engine = db_engine

    ...
```

```python
from typing import Optional

from sqlalchemy import Engine
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


### Authorization handler

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

Since we are using werkzeug exceptions, we will also need the `WerkzeugExceptionHandler` to serialize them correctly.
Let's put together an appropriate handler chain:

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


## Complete program

```python
from typing import Optional

from sqlalchemy import Engine, create_engine
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