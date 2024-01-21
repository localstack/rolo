import pytest

from rolo.gateway import RequestContext


def test_set_and_access_data():
    context = RequestContext()

    context.some_data = "foo"
    assert context.some_data == "foo"


def test_access_non_existing_data():
    context = RequestContext()

    with pytest.raises(AttributeError):
        assert context.some_data


def test_get_non_existing_data():
    context = RequestContext()

    assert context.get("some_data") is None


def test_set_and_get_data():
    context = RequestContext()

    context.some_data = "foo"
    assert context.get("some_data") is "foo"
    context.some_data = "bar"
    assert context.get("some_data") is "bar"
