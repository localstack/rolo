"""
This module enables the resource class pattern, where each respective ``on_<http_method>`` method of a class is
treated like an endpoint for the respective HTTP method. The following shows an example of how the pattern is used::

    class Foo:
        def on_get(self, request: Request):
            return {"ok": "GET it"}

        def on_post(self, request: Request):
            return {"ok": "it was POSTed"}


    router = Router(dispatcher=resource_dispatcher())
    router.add(Resource("/foo", Foo())
"""
from typing import Any, Iterable, Optional, Type

from werkzeug.routing import Map, Rule, RuleFactory

from .router import route

_resource_methods = [
    "on_head",  # it's important that HEAD rules are added first (werkzeug matching order)
    "on_get",
    "on_post",
    "on_put",
    "on_patch",
    "on_delete",
    "on_options",
    "on_trace",
]


def resource(path: str, host: Optional[str] = None, **kwargs):
    """
    Class decorator that turns every method that follows the pattern ``on_<http-method>`` into a route,
    where the allowed method for that route is automatically set to the method specified in the function name. Example
    when using a Router with the ``handler_dispatcher``::

        @resource("/myresource/<resource_id>")
        class MyResource:
            def on_get(request: Request, resource_id: str) -> Response:
                return Response(f"GET called on {resource_id}")

            def on_post(request: Request, resource_id: str) -> Response:
                return Response(f"POST called on {resource_id}")

    This class can then be added to a router via ``router.add_route_endpoints(MyResource())``.

    Note that, if an on_get method is present in the resource but on_head is not, then HEAD requests are automatically
    routed to ``on_get``. This replicates Werkzeug's behavior https://werkzeug.palletsprojects.com/en/2.2.x/routing/.

    :param path: the path pattern to match
    :param host: an optional host matching pattern. if not pattern is given, the rule matches any host
    :param kwargs: any other argument that can be passed to ``werkzeug.routing.Rule``
    :return: a class where each matching function is wrapped as a ``_RouteEndpoint``
    """
    kwargs.pop("methods", None)

    def _wrapper(cls: Type):
        for name in _resource_methods:
            member = getattr(cls, name, None)
            if member is None:
                continue

            http_method = name[3:].upper()
            setattr(cls, name, route(path, host, methods=[http_method], **kwargs)(member))

        return cls

    return _wrapper


class Resource(RuleFactory):
    """
    Exposes a given object that follows the "Resource" class pattern as a ``RuleFactory` that can then be added to a
    Router. Example use when using a Router with the ``handler_dispatcher``::

        class MyResource:
            def on_get(request: Request, resource_id: str) -> Response:
                return Response(f"GET called on {resource_id}")

            def on_post(request: Request, resource_id: str) -> Response:
                return Response(f"POST called on {resource_id}")

        router.add(Resource("/myresource/<resource_id>", MyResource()))

    Note that, if an on_get method is present in the resource but on_head is not, then HEAD requests are automatically
    routed to ``on_get``. This replicates Werkzeug's behavior https://werkzeug.palletsprojects.com/en/2.2.x/routing/.
    """

    def __init__(self, path: str, obj: Any, host: Optional[str] = None, **kwargs):
        self.path = path
        self.obj = obj
        self.host = host
        self.kwargs = kwargs

    def get_rules(self, map: Map) -> Iterable[Rule]:
        rules = []
        for name in _resource_methods:
            member = getattr(self.obj, name, None)
            if member is None:
                continue

            http_method = name[3:].upper()

            # If the member has rule_attributes (from @resource/@route decorator),
            # extract OpenAPI metadata and create rules with it
            if hasattr(member, "rule_attributes"):
                from .rules import _EndpointRule
                # Get the rule attributes for this member
                attrs = member.rule_attributes
                # Find attributes matching this HTTP method or use the first one
                matching_attr = None
                for attr in attrs:
                    if attr.methods and http_method in attr.methods:
                        matching_attr = attr
                        break
                if not matching_attr and attrs:
                    matching_attr = attrs[0]

                # Create rule using Resource's path, not the path from rule_attributes
                # This allows reusing the same endpoint at different paths
                if matching_attr:
                    for rule in _EndpointRule(
                        path=self.path,  # Use Resource's path, not matching_attr.path
                        endpoint=member,
                        host=self.host or matching_attr.host,
                        methods=[http_method],
                        **{**matching_attr.kwargs, **self.kwargs}  # Merge kwargs
                    ).get_rules(map):
                        rules.append(rule)
                else:
                    # Fallback if no matching attributes found
                    rules.append(
                        Rule(
                            self.path, endpoint=member, methods=[http_method], host=self.host, **self.kwargs
                        )
                    )
            else:
                # Otherwise, create a simple Rule
                rules.append(
                    Rule(
                        self.path, endpoint=member, methods=[http_method], host=self.host, **self.kwargs
                    )
                )
        return rules
