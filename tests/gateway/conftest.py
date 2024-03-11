import pytest

from rolo.gateway import Gateway
from rolo.testing.pytest import Server


@pytest.fixture
def serve_gateway(request):
    def _serve(gateway: Gateway) -> Server:
        try:
            gw_type = request.param
        except AttributeError:
            gw_type = "wsgi"

        if gw_type == "asgi":
            fixture = request.getfixturevalue("serve_asgi_gateway")
        elif gw_type == "twisted":
            fixture = request.getfixturevalue("serve_twisted_gateway")
        else:
            fixture = request.getfixturevalue("serve_wsgi_gateway")

        return fixture(gateway)

    yield _serve
