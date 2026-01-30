import json

import pytest
import requests

from rolo import Response
from rolo.gateway import Gateway, HandlerChain, RequestContext


@pytest.mark.parametrize("serve_gateway", ["asgi", "twisted"], indirect=True)
def test_raw_header_handling(serve_gateway):
    def handler(chain: HandlerChain, context: RequestContext, response: Response):
        response.data = json.dumps({"headers": dict(context.request.headers)})
        response.mimetype = "application/json"
        response.headers["X-fOO_bar"] = "FooBar"
        response.headers["content-md5"] = "af5e58f9a7c4682e1b410f2e9392a539"
        return response

    gateway = Gateway(request_handlers=[handler])

    srv = serve_gateway(gateway)

    response = requests.get(
        srv.url,
        headers={"x-mIxEd-CaSe": "myheader", "X-UPPER__CASE": "uppercase"},
    )
    request_headers = response.json()["headers"]

    # test default headers
    assert "User-Agent" in request_headers
    assert "Connection" in request_headers
    assert "Host" in request_headers

    # test custom headers
    assert "X-UPPER__CASE" in request_headers
    assert "x-mIxEd-CaSe" in request_headers

    response_headers = dict(response.headers)
    assert "X-fOO_bar" in response_headers
    # even though it's a standard header, it should be in the original case
    assert "content-md5" in response_headers
