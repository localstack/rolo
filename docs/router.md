Router
======

Routers are based on Werkzeug's [URL Map](https://werkzeug.palletsprojects.com/en/2.3.x/routing/), but dispatch to handler functions directly.
All features from Werkzeug's URL routing are inherited, including the [rule string format](https://werkzeug.palletsprojects.com/en/latest/routing/#rule-format) and [type converters](https://werkzeug.palletsprojects.com/en/latest/routing/#built-in-converters).

`@route`
--------

The `@route` decorator works similar to Flask or FastAPI, but they are not tied to an Application object.
Instead, you can define routes on functions or methods, and then add them directly to the router.

```python
from rolo import Router, route, Response
from werkzeug import Request
from werkzeug.serving import run_simple

@route("/users")
def list_users(_request: Request, args):
    assert not args
    return Response("user")

@route("/users/<int:user_id>")
def get_user_by_id(_request: Request, args):
    assert args
    return Response(f"{args['user_id']}")

router = Router()
router.add(list_users)
router.add(get_user_by_id)

# convert Router to a WSGI app and serve it through werkzeug
run_simple('localhost', 8080, router.wsgi(), use_reloader=True)
```

Depending on the _dispatcher_ your Router uses, the signature of your endpoints will look differently.

Handler dispatcher
------------------

Routers use dispatchers to dispatch the request to functions.
In the previous example, the default dispatcher calls the function with the `Request` object and the request arguments as dictionary.
The "handler dispatcher" can transform functions into more Flask or FastAPI-like functions, that also allow you to return values that are automatically transformed.

```python
from rolo import Router, route
from rolo.routing import handler_dispatcher

from werkzeug import Request
from werkzeug.serving import run_simple

@route("/users")
def list_users(request: Request):
    # query from db using the ?q= query string
    query = request.args["q"]
    # ...
    return [{"user_id": ...}, ...]

@route("/users/<int:user_id>")
def get_user_by_id(_request: Request, user_id: int):
    return {"user_id": user_id, "name": ...}

router = Router(dispatcher=handler_dispatcher())
router.add(list_users)
router.add(get_user_by_id)

# convert Router to a WSGI app and serve it through werkzeug
run_simple('localhost', 8080, router.wsgi(), use_reloader=True)
```

Using classes
-------------

Unlike Flask or FastAPI, Rolo allows you to use classes to organize your routes.
The above example can also be written as follows

```python
from rolo import Router, route, Request
from rolo.routing import handler_dispatcher

class UserResource:

    @route("/users/")
    def list_users(self, _request: Request):
        return "user"

    @route("/users/<int:user_id>")
    def get_user_by_id(self, _request: Request, user_id: int):
        return f"{user_id}"

router = Router(dispatcher=handler_dispatcher())
router.add(UserResource())
```
The router will scan the instantiated `UserResource` for `@route` decorators, and add them automatically.

Resource classes
----------------

If you prefer the RESTful style that `Falcon <https://falcon.readthedocs.io/en/stable/>`_ implements, you can use the `@resource` decorator on a class.
This will automatically create routes for all `on_<verb>` methods.
Here is an example


```python
from rolo import Router, resource, Request

@resource("/users/<int:user_id>")
class UserResource:

    def on_get(self, request: Request, user_id: int):
        return {"user_id": user_id, "user": ...}

    def on_post(self, request: Request, user_id: int):
        data = request.json
        # ... do something

router = Router()
router.add(UserResource())
```

Pydantic integration
--------------------

Here's how the default example from the FastAPI documentation would look like with rolo:

```python
import pydantic

from rolo import Request, Router, route


class Item(pydantic.BaseModel):
    name: str
    price: float
    is_offer: bool | None = None


@route("/", methods=["GET"])
def read_root(request: Request):
    return {"Hello": "World"}


@route("/items/<int:item_id>", methods=["GET"])
def read_item(request: Request, item_id: int):
    return {"item_id": item_id, "q": request.query_string}


@route("/items/<int:item_id>", methods=["PUT"])
def update_item(request: Request, item_id: int, item: Item):
    return {"item_name": item.name, "item_id": item_id}


router = Router(dispatcher=handler_dispatcher())
router.add(read_root)
router.add(read_item)
router.add(update_item)
```

Pydantic support in the Router is automatically enabled if rolo finds that pydantic is installed.