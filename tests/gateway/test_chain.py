from unittest import mock

from rolo.gateway import CompositeFinalizer, CompositeHandler, HandlerChain, RequestContext
from rolo.response import Response


def test_response_handler_exception():
    def _raise(*args, **kwargs):
        raise ValueError("oh noes")

    response1 = mock.MagicMock()
    response2 = _raise
    response3 = mock.MagicMock()
    exception = mock.MagicMock()
    finalizer = mock.MagicMock()

    chain = HandlerChain(
        response_handlers=[response1, response2, response3],
        exception_handlers=[exception],
        finalizers=[finalizer],
    )
    chain.handle(RequestContext(), Response())

    response1.assert_called_once()
    response3.assert_called_once()  # all response handlers should be called
    exception.assert_not_called()  # response handlers don't trigger exception handlers
    finalizer.assert_called_once()

    assert chain.error is None


def test_finalizer_handler_exception():
    def _raise(*args, **kwargs):
        raise ValueError("oh noes")

    response = mock.MagicMock()
    exception = mock.MagicMock()
    finalizer1 = mock.MagicMock()
    finalizer2 = _raise
    finalizer3 = mock.MagicMock()

    chain = HandlerChain(
        response_handlers=[response],
        exception_handlers=[exception],
        finalizers=[finalizer1, finalizer2, finalizer3],
    )
    chain.handle(RequestContext(), Response())

    response.assert_called_once()
    exception.assert_not_called()  # response handlers don't trigger exception handlers
    finalizer1.assert_called_once()
    finalizer3.assert_called_once()

    assert chain.error is None


def test_composite_finalizer_handler_exception():
    def _raise(*args, **kwargs):
        raise ValueError("oh noes")

    response = mock.MagicMock()
    exception = mock.MagicMock()
    finalizer1 = mock.MagicMock()
    finalizer2 = _raise
    finalizer3 = mock.MagicMock()

    finalizer = CompositeFinalizer()
    finalizer.append(finalizer1)
    finalizer.append(finalizer2)
    finalizer.append(finalizer3)

    chain = HandlerChain(
        response_handlers=[response],
        exception_handlers=[exception],
        finalizers=[finalizer],
    )
    chain.handle(RequestContext(), Response())

    response.assert_called_once()
    exception.assert_not_called()  # response handlers don't trigger exception handlers
    finalizer1.assert_called_once()
    finalizer3.assert_called_once()

    assert chain.error is None


class TestCompositeHandler:
    def test_composite_handler_stops_handler_chain(self):
        def inner1(_chain: HandlerChain, request: RequestContext, response: Response):
            _chain.stop()

        inner2 = mock.MagicMock()
        outer1 = mock.MagicMock()
        outer2 = mock.MagicMock()
        response1 = mock.MagicMock()
        finalizer = mock.MagicMock()

        chain = HandlerChain()

        composite = CompositeHandler()
        composite.handlers.append(inner1)
        composite.handlers.append(inner2)

        chain.request_handlers.append(outer1)
        chain.request_handlers.append(composite)
        chain.request_handlers.append(outer2)
        chain.response_handlers.append(response1)
        chain.finalizers.append(finalizer)

        chain.handle(RequestContext(), Response())
        outer1.assert_called_once()
        outer2.assert_not_called()
        inner2.assert_not_called()
        response1.assert_called_once()
        finalizer.assert_called_once()

    def test_composite_handler_terminates_handler_chain(self):
        def inner1(_chain: HandlerChain, request: RequestContext, response: Response):
            _chain.terminate()

        inner2 = mock.MagicMock()
        outer1 = mock.MagicMock()
        outer2 = mock.MagicMock()
        response1 = mock.MagicMock()
        finalizer = mock.MagicMock()

        chain = HandlerChain()

        composite = CompositeHandler()
        composite.handlers.append(inner1)
        composite.handlers.append(inner2)

        chain.request_handlers.append(outer1)
        chain.request_handlers.append(composite)
        chain.request_handlers.append(outer2)
        chain.response_handlers.append(response1)
        chain.finalizers.append(finalizer)

        chain.handle(RequestContext(), Response())
        outer1.assert_called_once()
        outer2.assert_not_called()
        inner2.assert_not_called()
        response1.assert_not_called()
        finalizer.assert_called_once()

    def test_composite_handler_with_not_return_on_stop(self):
        def inner1(_chain: HandlerChain, request: RequestContext, response: Response):
            _chain.stop()

        inner2 = mock.MagicMock()
        outer1 = mock.MagicMock()
        outer2 = mock.MagicMock()
        response1 = mock.MagicMock()
        finalizer = mock.MagicMock()

        chain = HandlerChain()

        composite = CompositeHandler(return_on_stop=False)
        composite.handlers.append(inner1)
        composite.handlers.append(inner2)

        chain.request_handlers.append(outer1)
        chain.request_handlers.append(composite)
        chain.request_handlers.append(outer2)
        chain.response_handlers.append(response1)
        chain.finalizers.append(finalizer)

        chain.handle(RequestContext(), Response())
        outer1.assert_called_once()
        outer2.assert_not_called()
        inner2.assert_called_once()
        response1.assert_called_once()
        finalizer.assert_called_once()

    def test_composite_handler_continues_handler_chain(self):
        inner1 = mock.MagicMock()
        inner2 = mock.MagicMock()
        outer1 = mock.MagicMock()
        outer2 = mock.MagicMock()
        response1 = mock.MagicMock()
        finalizer = mock.MagicMock()

        chain = HandlerChain()

        composite = CompositeHandler()
        composite.handlers.append(inner1)
        composite.handlers.append(inner2)

        chain.request_handlers.append(outer1)
        chain.request_handlers.append(composite)
        chain.request_handlers.append(outer2)
        chain.response_handlers.append(response1)
        chain.finalizers.append(finalizer)

        chain.handle(RequestContext(), Response())
        outer1.assert_called_once()
        outer2.assert_called_once()
        inner1.assert_called_once()
        inner2.assert_called_once()
        response1.assert_called_once()
        finalizer.assert_called_once()

    def test_composite_handler_exception_calls_outer_exception_handlers(self):
        def inner1(_chain: HandlerChain, request: RequestContext, response: Response):
            raise ValueError()

        inner2 = mock.MagicMock()
        outer1 = mock.MagicMock()
        outer2 = mock.MagicMock()
        exception_handler = mock.MagicMock()
        response1 = mock.MagicMock()
        finalizer = mock.MagicMock()

        chain = HandlerChain()

        composite = CompositeHandler()
        composite.handlers.append(inner1)
        composite.handlers.append(inner2)

        chain.request_handlers.append(outer1)
        chain.request_handlers.append(composite)
        chain.request_handlers.append(outer2)
        chain.exception_handlers.append(exception_handler)
        chain.response_handlers.append(response1)
        chain.finalizers.append(finalizer)

        chain.handle(RequestContext(), Response())
        outer1.assert_called_once()
        outer2.assert_not_called()
        inner2.assert_not_called()
        exception_handler.assert_called_once()
        response1.assert_called_once()
        finalizer.assert_called_once()
