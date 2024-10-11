import io

import requests

from rolo import Request, Response, Router, route
from rolo.dispatcher import handler_dispatcher
from rolo.gateway import Gateway
from rolo.gateway.handlers import RouterHandler


def test_large_file_upload(serve_twisted_gateway):
    router = Router(handler_dispatcher())

    @route("/hello", methods=["POST"])
    def hello(request: Request):
        return "ok"

    router.add(hello)

    gateway = Gateway(request_handlers=[RouterHandler(router, True)])
    server = serve_twisted_gateway(gateway)

    response = requests.post(server.url + "/hello", io.BytesIO(b"0" * 100001))

    assert response.status_code == 200


def test_full_absolute_form_uri(serve_twisted_gateway):
    import http.client

    router = Router(handler_dispatcher())

    @route("/hello", methods=["GET"])
    def hello(request: Request):
        if not request.path == "/hello" or not request.environ["RAW_URI"].startswith("http"):
            return Response(status=500)

        return "ok"

    router.add(hello)

    gateway = Gateway(request_handlers=[RouterHandler(router, True)])
    server = serve_twisted_gateway(gateway)
    host = server.url
    conn = http.client.HTTPConnection("", port=server.port)
    conn.set_debuglevel(1)
    # This is what is sent:
    # send: b'GET http://localhost:<port>/hello HTTP/1.1\r\nHost: localhost:<port>\r\nAccept-Encoding: identity\r\n\r\n'
    # note the full URI in the HTTP request
    conn.request("GET", url=f"{host}/hello")
    response = conn.getresponse()

    assert response.status == 200
