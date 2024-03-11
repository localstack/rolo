import json

import pytest
import requests

from rolo.gateway import Gateway, HandlerChain, RequestContext


@pytest.mark.parametrize("serve_gateway", ["asgi", "twisted"], indirect=True)
def test_raw_header_handling(serve_gateway):
    def handler(chain: HandlerChain, context: RequestContext, response):
        response.data = json.dumps({"headers": dict(context.request.headers)})
        response.mimetype = "application/json"
        response.headers["X-fOO_bar"] = "FooBar"
        return response

    gateway = Gateway(request_handlers=[handler])

    srv = serve_gateway(gateway)

    response = requests.get(
        srv.url,
        headers={"x-mIxEd-CaSe": "myheader", "X-UPPER__CASE": "uppercase"},
    )
    returned_headers = response.json()["headers"]
    assert "X-UPPER__CASE" in returned_headers
    assert "x-mIxEd-CaSe" in returned_headers
    assert "X-fOO_bar" in dict(response.headers)
