import logging
import typing as t

from ..request import Request
from ..response import Response
from ..websocket.websocket import WebSocketRequest
from .chain import ExceptionHandler, Handler, HandlerChain, RequestContext

LOG = logging.getLogger(__name__)


class Gateway:
    """
    A gateway creates new HandlerChain instances for each request and processes requests through them.
    """

    request_handlers: list[Handler]
    response_handlers: list[Handler]
    finalizers: list[Handler]
    exception_handlers: list[ExceptionHandler]

    def __init__(
        self,
        request_handlers: list[Handler] = None,
        response_handlers: list[Handler] = None,
        finalizers: list[Handler] = None,
        exception_handlers: list[ExceptionHandler] = None,
        context_class: t.Type[RequestContext] = None,
    ) -> None:
        super().__init__()
        self.request_handlers = request_handlers if request_handlers is not None else []
        self.response_handlers = response_handlers if response_handlers is not None else []
        self.exception_handlers = exception_handlers if exception_handlers is not None else []
        self.finalizers = finalizers if finalizers is not None else []
        self.context_class = context_class or RequestContext

    def new_chain(self) -> HandlerChain:
        return HandlerChain(
            self.request_handlers,
            self.response_handlers,
            self.finalizers,
            self.exception_handlers,
        )

    def process(self, request: Request, response: Response):
        chain = self.new_chain()

        context = self.context_class(request)

        chain.handle(context, response)

    def accept(self, request: WebSocketRequest):
        response = Response(status=101)
        self.process(request, response)

        # only send the populated response if the websocket hasn't already done so before
        if response.status_code != 101:
            if request.is_upgraded():
                return
            if request.is_rejected():
                return
            request.reject(response)
