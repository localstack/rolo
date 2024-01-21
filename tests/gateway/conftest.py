import pytest

from rolo.gateway import Gateway
from rolo.testing.pytest import Server


@pytest.fixture
def serve_gateway(request, serve_wsgi_gateway, serve_asgi_gateway):
    def _serve(gateway: Gateway) -> Server:
        try:
            gw_type = request.param
        except AttributeError:
            gw_type = "wsgi"

        if gw_type == "asgi":
            return serve_asgi_gateway(gateway)
        else:
            return serve_wsgi_gateway(gateway)

    return _serve
