import typing as t

from sqlalchemy import create_engine
from sqlmodel import SQLModel
from werkzeug.exceptions import Unauthorized

from rolo import Response, Router
from rolo.dispatcher import handler_dispatcher
from rolo.gateway import Gateway, HandlerChain, RequestContext
from rolo.gateway.handlers import RouterHandler, WerkzeugExceptionHandler
from rolo.gateway.wsgi import WsgiGateway

from .resource import HeroResource

if t.TYPE_CHECKING:
    from _typeshed.wsgi import WSGIApplication


class AuthorizationHandler:
    authorized_tokens: set[str]

    def __init__(self, authorized_tokens: set[str]):
        self.authorized_tokens = authorized_tokens

    def __call__(self, chain: HandlerChain, context: RequestContext, response: Response):
        auth = context.request.authorization

        if not auth:
            raise Unauthorized("No authorization header")
        if not auth.type == "bearer":
            raise Unauthorized("Unknown authorization type %s" % auth.type)
        if auth.token not in self.authorized_tokens:
            raise Unauthorized("Invalid token")


def wsgi() -> "WSGIApplication":
    # create engine
    engine = create_engine("sqlite:///database.db")
    SQLModel.metadata.create_all(engine)

    # create router with resource
    router = Router(handler_dispatcher())
    router.add(HeroResource(engine))

    # gateway
    gateway = Gateway(
        request_handlers=[
            AuthorizationHandler({"mysecret"}),
            RouterHandler(router, respond_not_found=True),
        ],
        exception_handlers=[
            WerkzeugExceptionHandler(output_format="json"),
        ]
    )

    return WsgiGateway(gateway)
