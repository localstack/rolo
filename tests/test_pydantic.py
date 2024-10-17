from typing import TypedDict

import pydantic
import pytest
from werkzeug.exceptions import BadRequest

from rolo import Request, Router, resource
from rolo.routing import handler as routing_handler
from rolo.routing import handler_dispatcher

pydantic_version = pydantic.version.version_short()


class MyItem(pydantic.BaseModel):
    name: str
    price: float
    is_offer: bool = None


class TestPydanticHandlerDispatcher:
    def test_request_arg(self):
        router = Router(dispatcher=handler_dispatcher())

        def handler(_request: Request, item: MyItem) -> dict:
            return {"item": item.model_dump()}

        router.add("/items", handler)

        request = Request("POST", "/items", body=b'{"name":"rolo","price":420.69}')
        assert router.dispatch(request).get_json(force=True) == {
            "item": {
                "name": "rolo",
                "price": 420.69,
                "is_offer": None,
            },
        }

    def test_request_args(self):
        router = Router(dispatcher=handler_dispatcher())

        def handler(_request: Request, item_id: int, item: MyItem) -> dict:
            return {"item_id": item_id, "item": item.model_dump()}

        router.add("/items/<int:item_id>", handler)

        request = Request("POST", "/items/123", body=b'{"name":"rolo","price":420.69}')
        assert router.dispatch(request).get_json(force=True) == {
            "item_id": 123,
            "item": {
                "name": "rolo",
                "price": 420.69,
                "is_offer": None,
            },
        }

    def test_request_args_empty_body(self):
        router = Router(dispatcher=handler_dispatcher())

        def handler(_request: Request, item_id: int, item: MyItem) -> dict:
            return {"item_id": item_id, "item": item.model_dump()}

        router.add("/items/<int:item_id>", handler)

        request = Request("POST", "/items/123", body=b"")
        assert router.dispatch(request).get_json(force=True) == [
            {
                "type": "json_invalid",
                "loc": [],
                "msg": "Invalid JSON: EOF while parsing a value at line 1 column 0",
                "ctx": {"error": "EOF while parsing a value at line 1 column 0"},
                "input": "",
                "url": f"https://errors.pydantic.dev/{pydantic_version}/v/json_invalid",
            }
        ]

    def test_response(self):
        router = Router(dispatcher=handler_dispatcher())

        def handler(_request: Request, item_id: int) -> MyItem:
            return MyItem(name="rolo", price=420.69)

        router.add("/items/<int:item_id>", handler)

        request = Request("GET", "/items/123")
        assert router.dispatch(request).get_json() == {
            "name": "rolo",
            "price": 420.69,
            "is_offer": None,
        }

    def test_response_list(self):
        router = Router(dispatcher=handler_dispatcher())

        def handler(_request: Request) -> list[MyItem]:
            return [
                MyItem(name="rolo", price=420.69),
                MyItem(name="twiks", price=1.23, is_offer=True),
            ]

        router.add("/items", handler)

        request = Request("GET", "/items")
        assert router.dispatch(request).get_json() == [
            {
                "name": "rolo",
                "price": 420.69,
                "is_offer": None,
            },
            {
                "name": "twiks",
                "price": 1.23,
                "is_offer": True,
            },
        ]

    def test_request_arg_validation_error(self):
        router = Router(dispatcher=handler_dispatcher())

        def handler(_request: Request, item_id: int, item: MyItem) -> str:
            return item.model_dump_json()

        router.add("/items/<int:item_id>", handler)

        request = Request("POST", "/items/123", body=b'{"name":"rolo"}')
        assert router.dispatch(request).get_json() == [
            {
                "type": "missing",
                "loc": ["price"],
                "msg": "Field required",
                "input": {"name": "rolo"},
                "url": f"https://errors.pydantic.dev/{pydantic_version}/v/missing",
            }
        ]

    def test_request_arg_invalid_json(self):
        router = Router(dispatcher=handler_dispatcher())

        def handler(_request: Request, item_id: int, item: MyItem) -> str:
            return item.model_dump_json()

        router.add("/items/<int:item_id>", handler)

        request = Request("POST", "/items/123", body=b'{"}')
        with pytest.raises(BadRequest):
            assert router.dispatch(request)

    def test_missing_annotation(self):
        router = Router(dispatcher=handler_dispatcher())

        # without an annotation, we cannot be sure what type to serialize into, so the dispatcher doesn't pass
        # anything into ``item``.
        def handler(_request: Request, item=None) -> dict:
            return {"item": item}

        router.add("/items", handler)

        request = Request("POST", "/items", body=b'{"name":"rolo","price":420.69}')
        assert router.dispatch(request).get_json(force=True) == {"item": None}

    def test_with_pydantic_disabled(self, monkeypatch):
        monkeypatch.setattr(routing_handler, "ENABLE_PYDANTIC", False)
        router = Router(dispatcher=handler_dispatcher())

        def handler(_request: Request, item: MyItem) -> dict:
            return {"item": item.model_dump()}

        router.add("/items", handler)

        request = Request("POST", "/items", body=b'{"name":"rolo","price":420.69}')
        with pytest.raises(TypeError):
            # "missing 1 required positional argument: 'item'"
            assert router.dispatch(request)

    def test_with_resource(self):
        router = Router(dispatcher=handler_dispatcher())

        @resource("/items/<int:item_id>")
        class MyResource:
            def on_get(self, request: Request, item_id: int):
                return MyItem(name="rolo", price=420.69)

            def on_post(self, request: Request, item_id: int, item: MyItem):
                return {"item_id": item_id, "item": item.model_dump()}

        router.add(MyResource())

        response = router.dispatch(Request("GET", "/items/123"))
        assert response.get_json() == {
            "name": "rolo",
            "price": 420.69,
            "is_offer": None,
        }

        response = router.dispatch(
            Request("POST", "/items/123", body=b'{"name":"rolo","price":420.69}')
        )
        assert response.get_json() == {
            "item": {"is_offer": None, "name": "rolo", "price": 420.69},
            "item_id": 123,
        }

    def test_with_generic_type_alias(self):
        router = Router(dispatcher=handler_dispatcher())

        def handler(request: Request, matrix: dict[str, str] = None):
            return "ok"

        router.add("/", endpoint=handler)

        request = Request("GET", "/")
        assert router.dispatch(request).data == b"ok"

    def test_with_typed_dict(self):
        try:
            from typing import Unpack
        except ImportError:
            pytest.skip("This test only works with Python >=3.11")

        router = Router(dispatcher=handler_dispatcher())

        class Test(TypedDict, total=False):
            path: str
            random_value: str

        def func(request: Request, **kwargs: Unpack[Test]):
            return f"path={kwargs.get('path')},random_value={kwargs.get('random_value')}"

        router.add(
            "/",
            endpoint=func,
            defaults={"path": "", "random_value": "dev"},
        )

        request = Request("GET", "/")
        assert router.dispatch(request).data == b"path=,random_value=dev"
