import io

import pytest
from werkzeug.exceptions import NotFound

from rolo import Response
from tests import static


def test_for_resource_html():
    response = Response.for_resource(static, "index.html")
    assert response.content_type == "text/html; charset=utf-8"
    assert response.get_data() == b'<html lang="en">\n<body>hello</body>\n</html>\n'
    assert response.status == "200 OK"


def test_for_resource_txt():
    response = Response.for_resource(static, "test.txt")
    assert response.content_type == "text/plain; charset=utf-8"
    assert response.get_data() == b"hello world\n"
    assert response.status == "200 OK"


def test_for_resource_with_custom_response_status_and_headers():
    response = Response.for_resource(static, "test.txt", status=201, headers={"X-Foo": "Bar"})
    assert response.content_type == "text/plain; charset=utf-8"
    assert response.get_data() == b"hello world\n"
    assert response.status == "201 CREATED"
    assert response.headers.get("X-Foo") == "Bar"


def test_for_resource_not_found():
    with pytest.raises(NotFound):
        Response.for_resource(static, "doesntexist.txt")


def test_for_json():
    response = Response.for_json(
        {"foo": "bar", "420": 69, "isTrue": True},
    )
    assert response.content_type == "application/json"
    assert response.get_data() == b'{"foo": "bar", "420": 69, "isTrue": true}'
    assert response.status == "200 OK"


def test_for_json_with_custom_response_status_and_headers():
    response = Response.for_json(
        {"foo": "bar", "420": 69, "isTrue": True},
        status=201,
        headers={"X-Foo": "Bar"},
    )
    assert response.content_type == "application/json"
    assert response.get_data() == b'{"foo": "bar", "420": 69, "isTrue": true}'
    assert response.status == "201 CREATED"
    assert response.headers.get("X-Foo") == "Bar"


@pytest.mark.parametrize(
    argnames="data",
    argvalues=[
        b"foobar",
        "foobar",
        io.BytesIO(b"foobar"),
        [b"foo", b"bar"],
    ],
)
def test_set_response(data):
    response = Response()
    response.set_response(data)
    assert response.get_data() == b"foobar"


def test_update_from():
    original = Response(
        [b"foo", b"bar"], 202, headers={"X-Foo": "Bar"}, mimetype="application/octet-stream"
    )

    response = Response()
    response.update_from(original)

    assert response.get_data() == b"foobar"
    assert response.status_code == 202
    assert response.headers.get("X-Foo") == "Bar"
    assert response.content_type == "application/octet-stream"
