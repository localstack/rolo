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

    def test_multi_values_headers(self, httpserver: HTTPServer):
        def multi_values_handler(_request: WerkzeugRequest) -> Response:
            multi_headers = Headers()
            multi_headers.add("Set-Cookie", "value1")
            multi_headers.add("Set-Cookie", "value2")
            assert multi_headers.getlist("Set-Cookie") == ["value1", "value2"]

            return Response(headers=multi_headers)

        httpserver.expect_request("/").respond_with_handler(multi_values_handler)

        url = httpserver.url_for("/")

        request = Request(path="/", method="GET")

        with SimpleRequestsClient() as client:
            response = client.request(request, url)
            assert response.headers.getlist("Set-Cookie") == ["value1", "value2"]

    def test_chunked_encoded_request(self, httpserver: HTTPServer):
        # because SimpleRequestsClient mostly forwards an existing incoming request, and it uses `restore_payload`
        # this means that any `Transfer-Encoding` headers must be stripped before sending

        def transfer_encoded_handler(_request: WerkzeugRequest) -> Response:
            return Response(response=_request.data)

        httpserver.expect_request("/").respond_with_handler(transfer_encoded_handler)

        url = httpserver.url_for("/")
        body = b"hello world"
        request = Request(
            path="/",
            method="POST",
            body=body,
            headers={
                "Transfer-Encoding": "chunked",
                "Content-Length": str(len(body)),
            },
        )

        with SimpleRequestsClient() as client:
            response = client.request(request, url)

        assert response.data == body

    def test_gzip_encoded_request(self, httpserver: HTTPServer):
        def transfer_encoded_handler(_request: WerkzeugRequest) -> Response:
            return Response(response=_request.data)

        httpserver.expect_request("/").respond_with_handler(transfer_encoded_handler)

        url = httpserver.url_for("/")
        raw_body = b"hello world"
        request = Request(
            path="/",
            method="POST",
            # we need to use the raw body here, because in real world use case, the webserver would have read and
            # decoded the payload
            body=raw_body,
            headers={
                "Transfer-Encoding": "gzip",
                "Content-Length": str(len(raw_body)),
            },
        )

        with SimpleRequestsClient() as client:
            response = client.request(request, url)

        assert response.data == raw_body
        # we're making sure we're not passing the `Transfer-Encoding` gzip along, as we're read the body and sent it
        # decoded over the wire
        assert "Transfer-Encoding" not in httpserver.log[0][0].headers
