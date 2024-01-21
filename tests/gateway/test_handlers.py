import pytest
import requests
from werkzeug import Request
from werkzeug.exceptions import BadRequest

from rolo import Response, Router
from rolo.gateway import Gateway, HandlerChain, RequestContext
from rolo.gateway.handlers import EmptyResponseHandler, RouterHandler, WerkzeugExceptionHandler


def _echo_handler(request: Request, args):
    return Response.for_json(
        {
            "path": request.path,
            "method": request.method,
            "headers": dict(request.headers),
        }
    )


@pytest.mark.parametrize("serve_gateway", ["wsgi", "asgi"], indirect=True)
class TestWerkzeugExceptionHandler:
    def test_json_output_format(self, serve_gateway):
        def handler(chain: HandlerChain, context: RequestContext, response: Response):
            if context.request.method != "GET":
                raise BadRequest("oh noes")

            chain.respond(payload="ok")

        server = serve_gateway(
            Gateway(
                request_handlers=[
                    handler,
                ],
                exception_handlers=[
                    WerkzeugExceptionHandler(),
                ],
            )
        )

        resp = requests.get(server.url)
        assert resp.status_code == 200
        assert resp.text == "ok"

        resp = requests.post(server.url)
        assert resp.status_code == 400
        assert resp.json() == {"code": 400, "description": "oh noes"}


@pytest.mark.parametrize("serve_gateway", ["wsgi", "asgi"], indirect=True)
class TestRouterHandler:
    def test_router_handler_with_respond_not_found(self, serve_gateway):
        router = Router()
        router.add("/foo", _echo_handler)

        server = serve_gateway(
            Gateway(
                request_handlers=[
                    RouterHandler(router, True),
                ],
            )
        )

        doc = requests.get(server.url + "/foo", headers={"Foo-Bar": "foobar"}).json()
        assert doc["path"] == "/foo"
        assert doc["method"] == "GET"
        assert doc["headers"]["Foo-Bar"] == "foobar"

        response = requests.get(server.url + "/bar")
        assert response.status_code == 404
        assert response.text == "not found"


@pytest.mark.parametrize("serve_gateway", ["wsgi", "asgi"], indirect=True)
class TestEmptyResponseHandler:
    def test_empty_response_handler(self, serve_gateway):
        def _handler(chain, context, response):
            if context.request.method == "GET":
                chain.respond(202, "ok")
            else:
                response.status_code = 0

        server = serve_gateway(
            Gateway(
                request_handlers=[_handler],
                response_handlers=[EmptyResponseHandler(status_code=412, body=b"teapot?")],
            )
        )

        response = requests.get(server.url)
        assert response.text == "ok"
        assert response.status_code == 202

        response = requests.post(server.url)
        assert response.text == "teapot?"
        assert response.status_code == 412
