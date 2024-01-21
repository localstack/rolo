"""
The core concepts of the HandlerChain.
"""
from __future__ import annotations

import logging
import typing as t

from werkzeug.datastructures import Headers

from rolo.request import Request
from rolo.response import Response

LOG = logging.getLogger(__name__)


class RequestContext:
    """
    A request context holds the original incoming HTTP Request and arbitrary data. It is passed through the handler
    chain and allows handlers to communicate.
    """

    request: Request

    def __init__(self, request: Request = None):
        self.request = request

    def __setattr__(self, key, value):
        self.__dict__[key] = value

    def __getattr__(self, item):
        try:
            return self.__dict__[item]
        except KeyError:
            pass
        raise AttributeError(f"'{self.__class__.__name__}' object has no attribute '{item}")

    def get(self, key: str) -> t.Optional[t.Any]:
        return self.__dict__.get(key)


RC = t.TypeVar("RC", bound=RequestContext)


class Handler(t.Protocol[RC]):
    """The signature of request or response handler in the handler chain. Receives the HandlerChain, the
    RequestContext, and the Response object to be populated."""

    def __call__(self, chain: "HandlerChain", context: RC, response: Response):
        ...


class ExceptionHandler(t.Protocol[RC]):
    """The signature of request or response handler in the handler chain. Receives the HandlerChain, the
    RequestContext, and the Response object to be populated."""

    def __call__(
        self, chain: "HandlerChain", exception: Exception, context: RC, response: Response
    ):
        ...


def call_safe(
    func: t.Callable, args: tuple = None, kwargs: dict = None, exception_message: str = None
) -> t.Optional[t.Any]:
    """
    Call the given function with the given arguments, and if it fails, log the given exception_message.
    If logging.DEBUG is set for the logger, then we also log the traceback.

    :param func: function to call
    :param args: arguments to pass
    :param kwargs: keyword arguments to pass
    :param exception_message: message to log on exception
    :return: whatever the func returns
    """
    if exception_message is None:
        exception_message = "error calling function %s" % func.__name__
    if args is None:
        args = ()
    if kwargs is None:
        kwargs = {}

    try:
        return func(*args, **kwargs)
    except Exception as e:
        if LOG.isEnabledFor(logging.DEBUG):
            LOG.exception(exception_message)
        else:
            LOG.warning("%s: %s", exception_message, e)


class HandlerChain(t.Generic[RC]):
    """
    Implements a variant of the chain-of-responsibility pattern to process an incoming HTTP request. A handler
    chain consists of request handlers, response handlers, finalizers, and exception handlers. Each request
    should have its own HandlerChain instance, since the handler chain holds state for the handling of a
    request. A chain can be in three states that can be controlled by the handlers.

    * Running - the implicit state where all handlers are executed sequentially
    * Stopped - a handler has called ``chain.stop()``. This stops the execution of all request handlers, and
      proceeds immediately to executing the response handlers. Response handlers and finalizers will be run,
      even if the chain has been stopped.
    * Terminated - a handler has called ``chain.terminate()`. This stops the execution of all request
      handlers, and all response handlers, but runs the finalizers at the end.

    If an exception occurs during the execution of request handlers, the chain by default stops the chain,
    then runs each exception handler, and finally runs the response handlers. Exceptions that happen during
    the execution of response or exception handlers are logged but do not modify the control flow of the
    chain.
    """

    # handlers
    request_handlers: list[Handler]
    response_handlers: list[Handler]
    finalizers: list[Handler]
    exception_handlers: list[ExceptionHandler]

    # behavior configuration
    stop_on_error: bool = True
    """If set to true, the chain will implicitly stop if an error occurs in a request handler."""
    raise_on_error: bool = False
    """If set to true, an exception in the request handler will be re-raised by ``handle`` after the exception
    handlers have been called. """

    # internal state
    stopped: bool
    terminated: bool
    error: t.Optional[Exception]
    response: t.Optional[Response]
    context: t.Optional[RequestContext]

    def __init__(
        self,
        request_handlers: list[Handler] = None,
        response_handlers: list[Handler] = None,
        finalizers: list[Handler] = None,
        exception_handlers: list[ExceptionHandler] = None,
    ) -> None:
        super().__init__()
        self.request_handlers = request_handlers if request_handlers is not None else []
        self.response_handlers = response_handlers if response_handlers is not None else []
        self.exception_handlers = exception_handlers if exception_handlers is not None else []
        self.finalizers = finalizers if finalizers is not None else []

        self.stopped = False
        self.terminated = False
        self.finalized = False
        self.error = None
        self.response = None
        self.context = None

    def handle(self, context: RC, response: Response):
        """
        Process the given request and populate the given response according to the handler chain control flow
        described in the ``HandlerChain`` class doc.

        :param context: the incoming request
        :param response: the response to be populated
        """
        self.context = context
        self.response = response

        try:
            for handler in self.request_handlers:
                try:
                    handler(self, self.context, response)
                except Exception as e:
                    # prepare the continuation behavior, but exception handlers could overwrite it
                    if self.raise_on_error:
                        self.error = e
                    if self.stop_on_error:
                        self.stopped = True

                    # call exception handlers safely
                    self._call_exception_handlers(e, response)

                # decide next step
                if self.error:
                    raise self.error
                if self.terminated:
                    return
                if self.stopped:
                    break

            # call response filters
            self._call_response_handlers(response)
        finally:
            if not self.finalized:
                self._call_finalizers(response)

    def respond(self, status_code: int = 200, payload: t.Any = None, headers: Headers = None):
        """
        Convenience method for handlers to stop the chain and set the given status and payload to the
        current response object.

        :param status_code: the HTTP status code
        :param payload: the payload of the response
        :param headers: additional headers
        """
        self.response.status_code = status_code
        if isinstance(payload, (list, dict)):
            self.response.set_json(payload)
        elif isinstance(payload, (str, bytes, bytearray)):
            self.response.data = payload
        elif payload is None and not self.response.response:
            self.response.response = []
        else:
            self.response.response = payload

        if headers:
            self.response.headers.update(headers)

        self.stop()

    def stop(self) -> None:
        """
        Stop the processing of the request handlers and proceed with response handlers.
        """
        self.stopped = True

    def terminate(self) -> None:
        """
        Terminate the handler chain, which skips response handlers.
        """
        self.terminated = True

    def throw(self, error: Exception) -> None:
        """
        Raises the given exception after the current request handler is done. This has no effect in response handlers.
        :param error: the exception to raise
        """
        self.error = error

    def _call_response_handlers(self, response):
        for handler in self.response_handlers:
            if self.terminated:
                return

            try:
                handler(self, self.context, response)
            except Exception as e:
                msg = "exception while running response handler"
                if LOG.isEnabledFor(logging.DEBUG):
                    LOG.exception(msg)
                else:
                    LOG.warning(msg + ": %s", e)

    def _call_finalizers(self, response):
        for handler in self.finalizers:
            try:
                handler(self, self.context, response)
            except Exception as e:
                msg = "exception while running request finalizer"
                if LOG.isEnabledFor(logging.DEBUG):
                    LOG.exception(msg)
                else:
                    LOG.warning(msg + ": %s", e)

    def _call_exception_handlers(self, e, response):
        for exception_handler in self.exception_handlers:
            try:
                exception_handler(self, e, self.context, response)
            except Exception as nested:
                # make sure we run all exception handlers
                msg = "exception while running exception handler"
                if LOG.isEnabledFor(logging.DEBUG):
                    LOG.exception(msg)
                else:
                    LOG.warning(msg + ": %s", nested)


class CompositeHandler:
    """
    A handler that sequentially invokes a list of Handlers, forming a stripped-down version of a handler
    chain.
    """

    handlers: list[Handler]

    def __init__(self, return_on_stop=True) -> None:
        """
        Creates a new composite handler with an empty handler list.

        TODO: build a proper chain nesting mechanism.

        :param return_on_stop: whether to respect chain.stopped
        """
        super().__init__()
        self.handlers = []
        self.return_on_stop = return_on_stop

    def append(self, handler: Handler) -> None:
        """
        Adds the given handler to the list of handlers.

        :param handler: the handler to add
        """
        self.handlers.append(handler)

    def remove(self, handler: Handler) -> None:
        """
        Remove the given handler from the list of handlers
        :param handler: the handler to remove
        """
        self.handlers.remove(handler)

    def __call__(self, chain: HandlerChain, context: RequestContext, response: Response):
        for handler in self.handlers:
            handler(chain, context, response)

            if chain.terminated:
                return
            if chain.stopped and self.return_on_stop:
                return


class CompositeExceptionHandler:
    """
    A exception handler that sequentially invokes a list of ExceptionHandler instances, forming a
    stripped-down version of a handler chain for exception handlers.
    """

    handlers: t.List[ExceptionHandler]

    def __init__(self) -> None:
        """
        Creates a new composite exception handler with an empty handler list.
        """
        self.handlers = []

    def append(self, handler: ExceptionHandler) -> None:
        """
        Adds the given handler to the list of handlers.

        :param handler: the handler to add
        """
        self.handlers.append(handler)

    def remove(self, handler: ExceptionHandler) -> None:
        """
        Remove the given handler from the list of handlers
        :param handler: the handler to remove
        """
        self.handlers.remove(handler)

    def __call__(
        self, chain: HandlerChain, exception: Exception, context: RequestContext, response: Response
    ):
        for handler in self.handlers:
            call_safe(
                handler,
                args=(chain, exception, context, response),
                exception_message="exception while running exception handler",
            )


class CompositeResponseHandler(CompositeHandler):
    """
    A CompositeHandler that by default does not return on stop, meaning that all handlers in the composite
    will be executed, even if one of the handlers has called ``chain.stop()``. This mimics how response
    handlers are executed in the ``HandlerChain``.
    """

    def __init__(self) -> None:
        super().__init__(return_on_stop=False)


class CompositeFinalizer(CompositeResponseHandler):
    """
    A CompositeHandler that uses ``call_safe`` to invoke handlers, so every handler is always executed.
    """

    def __call__(self, chain: HandlerChain, context: RequestContext, response: Response):
        for handler in self.handlers:
            call_safe(
                handler,
                args=(chain, context, response),
                exception_message="Error while running request finalizer",
            )
