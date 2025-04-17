from pytest_httpserver import HTTPServer
from werkzeug import Request as WerkzeugRequest
from werkzeug.datastructures import Headers

from rolo import Response
from rolo.client import SimpleRequestsClient
from rolo.request import Request


def echo_request_metadata_handler(request: WerkzeugRequest) -> Response:
    """
    Simple request handler that returns the incoming request metadata (method, path, url, headers).

    :param request: the incoming HTTP request
    :return: an HTTP response
    """
    response = Response()
    response.set_json(
        {
            "method": request.method,
            "path": request.path,
            "url": request.url,
            "headers": dict(Headers(request.headers)),
        }
    )
    return response


class TestSimpleRequestClient:
    def test_empty_accept_encoding_header(self, httpserver: HTTPServer):
        httpserver.expect_request("/").respond_with_handler(echo_request_metadata_handler)

        url = httpserver.url_for("/")

        request = Request(path="/", method="GET")

        with SimpleRequestsClient() as client:
            response = client.request(request, url)

        assert "Accept-Encoding" not in response.json["headers"]
        assert "accept-encoding" not in response.json["headers"]
