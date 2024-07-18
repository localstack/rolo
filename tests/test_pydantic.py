import pydantic
import pytest

from rolo import Request, Router, dispatcher, resource
from rolo.dispatcher import handler_dispatcher


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
                "url": "https://errors.pydantic.dev/2.8/v/json_invalid",
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
                "url": "https://errors.pydantic.dev/2.8/v/missing",
            }
        ]

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
        monkeypatch.setattr(dispatcher, "ENABLE_PYDANTIC", False)
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
