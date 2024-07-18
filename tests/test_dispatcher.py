from typing import Any, Dict

import pydantic
import pytest
from werkzeug.exceptions import NotFound

from rolo import Request, Response, Router
from rolo.dispatcher import handler_dispatcher


class TestHandlerDispatcher:
    def test_handler_dispatcher(self):
        router = Router(dispatcher=handler_dispatcher())

        def handler_foo(_request: Request) -> Response:
            return Response("ok")

        def handler_bar(_request: Request, bar, baz) -> Response:
            response = Response()
            response.set_json({"bar": bar, "baz": baz})
            return response

        router.add("/foo", handler_foo)
        router.add("/bar/<int:bar>/<baz>", handler_bar)

        assert router.dispatch(Request("GET", "/foo")).data == b"ok"
        assert router.dispatch(Request("GET", "/bar/420/ed")).json == {"bar": 420, "baz": "ed"}

        with pytest.raises(NotFound):
            assert router.dispatch(Request("GET", "/bar/asfg/ed"))

    def test_handler_dispatcher_invalid_signature(self):
        router = Router(dispatcher=handler_dispatcher())

        def handler(_request: Request, arg1) -> Response:  # invalid signature
            return Response("ok")

        router.add("/foo/<arg1>/<arg2>", handler)

        with pytest.raises(TypeError):
            router.dispatch(Request("GET", "/foo/a/b"))

    def test_handler_dispatcher_with_dict_return(self):
        router = Router(dispatcher=handler_dispatcher())

        def handler(_request: Request, arg1) -> Dict[str, Any]:
            return {"arg1": arg1, "hello": "there"}

        router.add("/foo/<arg1>", handler)
        assert router.dispatch(Request("GET", "/foo/a")).json == {"arg1": "a", "hello": "there"}

    def test_handler_dispatcher_with_list_return(self):
        router = Router(dispatcher=handler_dispatcher())

        def handler(_request: Request, arg1) -> Dict[str, Any]:
            return [{"arg1": arg1, "hello": "there"}, 1, 2, "3", [4, 5]]

        router.add("/foo/<arg1>", handler)
        assert router.dispatch(Request("GET", "/foo/a")).json == [
            {"arg1": "a", "hello": "there"},
            1,
            2,
            "3",
            [4, 5],
        ]

    def test_handler_dispatcher_with_text_return(self):
        router = Router(dispatcher=handler_dispatcher())

        def handler(_request: Request, arg1) -> str:
            return f"hello: {arg1}"

        router.add("/<arg1>", handler)
        assert router.dispatch(Request("GET", "/world")).data == b"hello: world"

    def test_handler_dispatcher_with_none_return(self):
        router = Router(dispatcher=handler_dispatcher())

        def handler(_request: Request):
            return None

        router.add("/", handler)
        assert router.dispatch(Request("GET", "/")).status_code == 200


class TestPydanticHandlerDispatcher:
    def test_request_arg(self):
        router = Router(dispatcher=handler_dispatcher())

        class MyItem(pydantic.BaseModel):
            name: str
            price: float
            is_offer: bool = None

        def handler(_request: Request, item_id: int, item: MyItem) -> str:
            return item.model_dump_json()

        router.add("/items/<item_id>", handler)

        request = Request("POST", "/items/123", body=b'{"name":"rolo","price":420.69}')
        assert router.dispatch(request).data == b'{"name":"rolo","price":420.69,"is_offer":null}'

    def test_response(self):
        router = Router(dispatcher=handler_dispatcher())

        class MyItem(pydantic.BaseModel):
            name: str
            price: float
            is_offer: bool = None

        def handler(_request: Request, item_id: int) -> MyItem:
            return MyItem(name="rolo", price=420.69)

        router.add("/items/<item_id>", handler)

        request = Request("GET", "/items/123")
        assert router.dispatch(request).get_json() == {
            "name": "rolo",
            "price": 420.69,
            "is_offer": None,
        }

    def test_request_arg_validation_error(self):
        router = Router(dispatcher=handler_dispatcher())

        class MyItem(pydantic.BaseModel):
            name: str
            price: float
            is_offer: bool = None

        def handler(_request: Request, item_id: int, item: MyItem) -> str:
            return item.model_dump_json()

        router.add("/items/<item_id>", handler)

        request = Request("POST", "/items/123", body=b'{"name":"rolo"}')
        assert router.dispatch(request).get_json() == [
            {
                "type": "missing",
                "loc": ["price"],
                "msg": "Field required",
                "input": {"name": "rolo"},
                "url": "https://errors.pydantic.dev/2.8/v/missing",
            }
        ]
