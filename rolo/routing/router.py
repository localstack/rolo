import functools
import threading
import typing as t
from typing import overload

from werkzeug import Request, Response
from werkzeug.routing import BaseConverter, Map, Rule, RuleFactory

from rolo.request import get_raw_path

from .converter import PortConverter, RegexConverter
from .rules import RuleAdapter, _RouteEndpoint, _RuleAttributes

if t.TYPE_CHECKING:
    from _typeshed.wsgi import WSGIApplication

HTTP_METHODS = ("GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS", "TRACE")

E = t.TypeVar("E")
RequestArguments = t.Mapping[str, t.Any]


class Dispatcher(t.Protocol[E]):
    """
    A Dispatcher is called when a URL route matches a request. The dispatcher is responsible for appropriately
    creating a Response from the incoming Request and the matching endpoint.
    """

    def __call__(self, request: Request, endpoint: E, args: RequestArguments) -> Response:
        """
        Dispatch the HTTP Request.

        :param request: the incoming HTTP request
        :param endpoint: the endpoint that matched the URL rule
        :param args: the request arguments extracted from the URL rule
        :return: an HTTP Response
        """
        pass


def route(
    path: str, host: t.Optional[str] = None, methods: t.Optional[t.Iterable[str]] = None, **kwargs
) -> t.Callable[[E], list[_RouteEndpoint]]:
    """
    Decorator that indicates that the given function is a Router Rule.

    :param path: the path pattern to match
    :param host: an optional host matching pattern. if not pattern is given, the rule matches any host
    :param methods: the allowed HTTP methods for this rule
    :param kwargs: any other argument that can be passed to ``werkzeug.routing.Rule``
    :return: the function endpoint wrapped as a ``_RouteEndpoint``
    """

    def wrapper(fn: E):
        if hasattr(fn, "rule_attributes"):
            route_marker = fn
        else:

            @functools.wraps(fn)
            def route_marker(*args, **kwargs):
                return fn(*args, **kwargs)

            route_marker.rule_attributes = []

        route_marker.rule_attributes.append(_RuleAttributes(path, host, methods, kwargs))

        return route_marker

    return wrapper


def call_endpoint(
    request: Request,
    endpoint: t.Callable[[Request, RequestArguments], Response],
    args: RequestArguments,
) -> Response:
    """
    A Dispatcher that treats the matching endpoint as a callable and invokes it with the Request and request arguments.
    """
    return endpoint(request, args)


def _clone_map_without_rules(old: Map) -> Map:
    return Map(
        default_subdomain=old.default_subdomain,
        strict_slashes=old.strict_slashes,
        merge_slashes=old.merge_slashes,
        redirect_defaults=old.redirect_defaults,
        converters=old.converters,
        sort_parameters=old.sort_parameters,
        sort_key=old.sort_key,
        host_matching=old.host_matching,
    )


def _clone_map_with_rules(old: Map) -> Map:
    """
    Creates a new copy of the existing map, with fresh unbound copies of all its containing rules.

    :param old: the map to copy
    :return: a new instance of the map
    """
    new = _clone_map_without_rules(old)

    for old_rule in old.iter_rules():
        new.add(old_rule.empty())

    return new


class Router(t.Generic[E]):
    """
    A Router is a wrapper around werkzeug's routing Map, that adds convenience methods and additional dispatching
    logic via the ``Dispatcher`` Protocol.
    """

    default_converters: dict[str, t.Type[BaseConverter]] = {
        "regex": RegexConverter,
        "port": PortConverter,
    }

    url_map: Map
    dispatcher: Dispatcher[E]

    def __init__(
        self,
        dispatcher: Dispatcher[E] = None,
        converters: t.Mapping[str, t.Type[BaseConverter]] = None,
    ):
        if converters is None:
            converters = dict(self.default_converters)
        else:
            converters = {**self.default_converters, **converters}

        self.url_map = Map(
            host_matching=True,
            strict_slashes=False,
            converters=converters,
            redirect_defaults=False,
        )
        self.dispatcher = dispatcher or call_endpoint
        self._mutex = threading.RLock()

    @overload
    def add(
        self,
        path: str,
        endpoint: E,
        host: t.Optional[str] = None,
        methods: t.Optional[t.Iterable[str]] = None,
        **kwargs,
    ) -> Rule:
        """
        Creates a new Rule from the given parameters and adds it to the URL Map.

        TODO: many callers still expect ``add`` to return a single rule rather than a list, but it would be better to
         homogenize the API and make every method return a list.

        :param path: the path pattern to match. This path rule, in contrast to the default behavior of Werkzeug, will be
                        matched against the raw / original (potentially URL-encoded) path.
        :param endpoint: the endpoint to invoke
        :param host: an optional host matching pattern. if not pattern is given, the rule matches any host
        :param methods: the allowed HTTP verbs for this rule
        :param kwargs: any other argument that can be passed to ``werkzeug.routing.Rule``
        :return: the rule that was created
        """
        ...

    @overload
    def add(self, fn: _RouteEndpoint) -> list[Rule]:
        """
        Adds a RouteEndpoint (typically a function decorated with ``@route``) as a rule to the router.

        :param fn: the RouteEndpoint function
        :return: the rules that were added. for this operation, only one rule will be in the list
        """
        ...

    @overload
    def add(self, rule_factory: RuleFactory) -> list[Rule]:
        """
        Adds a ``Rule`` or the rules created by a ``RuleFactory`` to the given router. It passes the rules down to
        the underlying Werkzeug ``Map``, but also returns the created Rules.

        :param rule_factory: a `Rule` or ``RuleFactory`
        :return: the rules that were added
        """
        ...

    @overload
    def add(self, obj: t.Any) -> list[Rule]:
        """
        Scans the given object for members that can be used as a `RouteEndpoint` and adds them to the router.

        :param obj: the object to scan
        :return: the rules that were added
        """
        ...

    @overload
    def add(self, routes: list[t.Union[_RouteEndpoint, RuleFactory, t.Any]]) -> list[Rule]:
        """
        Add multiple routes or rules to the router at once.

        :param routes: the objects to add as routes
        :return: the rules that were added
        """
        ...

    def add(self, *args, **kwargs) -> t.Union[Rule, list[Rule]]:
        """
        Creates a ``RuleAdapter`` and adds the generated rules to the router's Map.
        """
        rules = self._add_rules(RuleAdapter(*args, **kwargs))

        if "path" in kwargs or isinstance(args[0], str):
            return rules[0]

        return rules

    def _add_rules(self, rule_factory: RuleFactory) -> list[Rule]:
        """
        Thread safe version of Werkzeug's ``Map.add``.

        :param rule_factory: the rule to add
        """
        with self._mutex:
            new = _clone_map_with_rules(self.url_map)

            # instantiate, modify, and collect rules
            rules = []
            for rule in rule_factory.get_rules(new):
                rules.append(rule)

                if rule.host is None and new.host_matching:
                    # this creates a "match any" rule, and will put the value of the host
                    # into the variable "__host__"
                    rule.host = "<__host__>"

            for rule in rules:
                new.add(rule)

            self.url_map = new

            return rules

    def add_rule(self, rule: RuleFactory):
        """
        Thread safe version of Werkzeug's ``Map.add``. This can be used as low-level method to pass a rule directly
        to the Werkzeug URL map without any manipulation or manual creation of the rule, which ``add`` does. Like
        ``remove``, the method actually clones and replaces the underlying URL Map, to guarantee thread safety with
        ``dispatch``. Adding rules is therefore a relatively expensive operation.

        :param rule: the rule to add
        """
        with self._mutex:
            new = _clone_map_with_rules(self.url_map)
            new.add(rule)
            self.url_map = new

    def remove(self, rules: t.Union[Rule, t.Iterable[Rule]]):
        """
        Removes a single Rule from the Router.

        **Caveat**: This is an expensive operation. Removing rules from a URL Map is intentionally not supported by
        werkzeug due to issues with thread safety, see https://github.com/pallets/werkzeug/issues/796, and because
        using a lock in ``match`` would be too expensive. However, some services that use Routers for routing
        internal resources need to be able to remove rules when those resources are removed. So to remove rules we
        create a new Map without that rule. This will not prevent the rules from dispatching until the Map has been
        completely constructed.

        :param rules: the Rule or rules to remove that were previously returned by ``add``.
        """
        if isinstance(rules, Rule):
            self._remove_rules([rules])
        else:
            self._remove_rules(rules)

    def _remove_rules(self, rules: t.Iterable[Rule]):
        """
        Removes a set of Rules from the Router.

        **Caveat**: This is an expensive operation. Removing rules from a URL Map is intentionally not supported by
        werkzeug due to issues with thread safety, see https://github.com/pallets/werkzeug/issues/796, and because
        using a lock in ``match`` would be too expensive. However, some services that use Routers for routing
        internal resources need to be able to remove rules when those resources are removed. So to remove rules we
        create a new Map without that rule. This will not prevent the rules from dispatching until the Map has been
        completely constructed.

        :param rules: the list of Rule objects to remove that were previously returned by ``add``.
        """
        with self._mutex:
            old = self.url_map
            for r in rules:
                if r not in old._rules:
                    raise KeyError("no such rule")

            # collect all old rules that are not in the set of rules to remove
            new = _clone_map_without_rules(old)

            for old_rule in old.iter_rules():
                if old_rule in rules:
                    # this works even with copied rules because of the __eq__ implementation of Rule
                    continue

                new.add(old_rule.empty())
            self.url_map = new

    def dispatch(self, request: Request) -> Response:
        """
        Does the entire dispatching roundtrip, from matching the request to endpoints, and then invoking the endpoint
        using the configured dispatcher of the router. For more information on the matching behavior,
        see ``werkzeug.routing.MapAdapter.match()``.

        :param request: the HTTP request
        :return: the HTTP response
        """
        matcher = self.url_map.bind(server_name=request.host)
        # Match on the _raw_ path to ensure that converters (like "path") can extract the raw path.
        # f.e. router.add(/<path:path>, ProxyHandler(...))
        # If we would use the - already url-decoded - request.path here, a handler would not be able to access
        # the original (potentially URL-encoded) path.
        # As a consequence, rules need to match on URL-encoded URLs (f.e. use '%20' instead of ' ').
        handler, args = matcher.match(get_raw_path(request), method=request.method)
        args.pop("__host__", None)
        return self.dispatcher(request, handler, args)

    def route(
        self,
        path: str,
        host: t.Optional[str] = None,
        methods: t.Optional[t.Iterable[str]] = None,
        **kwargs,
    ) -> t.Callable[[E], _RouteEndpoint]:
        """
        Returns a ``route`` decorator and immediately adds it to the router instance. This effectively mimics flask's
        ``@app.route``.

        :param path: the path pattern to match
        :param host: an optional host matching pattern. if not pattern is given, the rule matches any host
        :param methods: the allowed HTTP verbs for this rule
        :param kwargs: any other argument that can be passed to ``werkzeug.routing.Rule``
        :return: the function endpoint wrapped as a ``_RouteEndpoint``
        """

        def wrapper(fn):
            r = route(path, host, methods, **kwargs)
            fn = r(fn)
            self.add(fn)
            return fn

        return wrapper

    def wsgi(self) -> "WSGIApplication":
        """
        Returns this router as a WSGI compatible interface. This can be used to conveniently serve a Router instance
        through a WSGI server, for instance werkzeug's dev server::

            from werkzeug.serving import run_simple

            from rolo import Router
            from rolo.dispatcher import handler_dispatcher

            router = Router(dispatcher=handler_dispatcher())
            run_simple("localhost", 5000, router.wsgi())

        :return: a WSGI callable that invokes this router
        """
        return Request.application(self.dispatch)
