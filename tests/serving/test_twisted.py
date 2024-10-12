import http.client
import io
import json

import requests

from rolo import Request, Router, route
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
    router = Router(handler_dispatcher())

    @route("/hello", methods=["GET"])
    def hello(request: Request):
        return {"path": request.path, "raw_uri": request.environ["RAW_URI"]}

    router.add(hello)

    gateway = Gateway(request_handlers=[RouterHandler(router, True)])
    server = serve_twisted_gateway(gateway)
    host = server.url

    conn = http.client.HTTPConnection(host="127.0.0.1", port=server.port)

    # This is what is sent:
    # send: b'GET http://localhost:<port>/hello HTTP/1.1\r\nHost: localhost:<port>\r\nAccept-Encoding: identity\r\n\r\n'
    # note the full URI in the HTTP request
    conn.request("GET", url=f"{host}/hello")
    response = conn.getresponse()

    assert response.status == 200
    response_data = json.loads(response.read())
    assert response_data["path"] == "/hello"
    assert response_data["raw_uri"].startswith("http")
