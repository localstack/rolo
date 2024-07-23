import io

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
