import inspect
import typing as t

from werkzeug.routing import Map, Rule, RuleFactory


class _RuleAttributes(t.NamedTuple):
    path: str
    host: t.Optional[str] = (None,)
    methods: t.Optional[t.Iterable[str]] = None
    kwargs: t.Optional[dict[str, t.Any]] = {}


class _RouteEndpoint(t.Protocol):
    """
    An endpoint that encapsulates ``_RuleAttributes`` for the creation of a ``Rule`` inside a ``Router``.
    """

    rule_attributes: list[_RuleAttributes]

    def __call__(self, *args, **kwargs):
        raise NotImplementedError


class WithHost(RuleFactory):
    def __init__(self, host: str, rules: t.Iterable[RuleFactory]) -> None:
        self.host = host
        self.rules = rules

    def get_rules(self, map: Map) -> t.Iterator[Rule]:
        for rulefactory in self.rules:
            for rule in rulefactory.get_rules(map):
                rule = rule.empty()
                rule.host = self.host
                yield rule


class RuleGroup(RuleFactory):
    def __init__(self, rules: t.Iterable[RuleFactory]):
        self.rules = rules

    def get_rules(self, map: Map) -> t.Iterable[Rule]:
        for rule in self.rules:
            yield from rule.get_rules(map)


class RuleAdapter(RuleFactory):
    """
    Takes something that can also be passed to ``Router.add``, and exposes it as a ``RuleFactory`` that generates the
    appropriate Werkzeug rules. This can be used in combination with other rule factories like ``Submount``,
    and creates general compatibility with werkzeug rules. Here's an example::

        @route("/my_api", methods=["GET"])
        def do_get(request: Request, _args):
            # should be inherited
            return Response(f"{request.path}/do-get")

        def hello(request: Request, _args):
            return Response(f"hello world")

        router = Router()

        # base endpoints
        endpoints = RuleAdapter([
            do_get,
            RuleAdapter("/hello", hello)
        ])

        router.add([
            endpoints,
            Submount("/foo", [endpoints])
        ])

    """

    factory: RuleFactory
    """The underlying real rule factory."""

    @t.overload
    def __init__(
        self,
        path: str,
        endpoint: t.Callable,
        host: t.Optional[str] = None,
        methods: t.Optional[t.Iterable[str]] = None,
        **kwargs,
    ):
        """
        Basically a ``Rule``.

        :param path: the path pattern to match. This path rule, in contrast to the default behavior of Werkzeug, will be
                        matched against the raw / original (potentially URL-encoded) path.
        :param endpoint: the endpoint to invoke
        :param host: an optional host matching pattern. if not pattern is given, the rule matches any host
        :param methods: the allowed HTTP verbs for this rule
        :param kwargs: any other argument that can be passed to ``werkzeug.routing.Rule``
        """
        ...

    @t.overload
    def __init__(self, fn: _RouteEndpoint):
        """
        Takes a route endpoint (typically a function decorated with ``@route``) and adds it as ``EndpointRule``.

        :param fn: the RouteEndpoint function
        """
        ...

    @t.overload
    def __init__(self, rule_factory: RuleFactory):
        """
        Adds a ``Rule`` or the rules created by a ``RuleFactory`` to the given router. It passes the rules down to
        the underlying Werkzeug ``Map``, but also returns the created Rules.

        :param rule_factory: a `Rule` or ``RuleFactory`
        """
        ...

    @t.overload
    def __init__(self, obj: t.Any):
        """
        Scans the given object for members that can be used as a `RouteEndpoint` and adds them to the router.

        :param obj: the object to scan
        """
        ...

    @t.overload
    def __init__(self, rules: list[t.Union[_RouteEndpoint, RuleFactory, t.Any]]):
        """Add multiple rules at once"""
        ...

    def __init__(self, *args, **kwargs):
        """
        Dispatcher for overloaded ``__init__`` methods.
        """
        if "path" in kwargs or isinstance(args[0], str):
            self.factory = _EndpointRule(*args, **kwargs)
        elif "fn" in kwargs or callable(args[0]):
            self.factory = _EndpointFunction(*args, **kwargs)
        elif "rule_factory" in kwargs:
            self.factory = kwargs["rule_factory"]
        elif isinstance(args[0], RuleFactory):
            self.factory = args[0]
        elif isinstance(args[0], list):
            self.factory = RuleGroup([RuleAdapter(rule) for rule in args[0]])
        else:
            self.factory = _EndpointsObject(*args, **kwargs)

    def get_rules(self, map: Map) -> t.Iterable[Rule]:
        yield from self.factory.get_rules(map)


class _EndpointRule(RuleFactory):
    """
    Generates default werkzeug ``Rule`` object with the given attributes. Additionally, it makes sure that
    the generated rule always has a default host value, if the map has host matching enabled. Specifically,
    it adds the well-known placeholder ``<__host__>``, which is later stripped out of the request arguments
    when dispatching to the endpoint. This ensures compatibility of rule definitions across routers that
    have host matching enabled or not.
    """

    def __init__(
        self,
        path: str,
        endpoint: t.Callable,
        host: t.Optional[str] = None,
        methods: t.Optional[t.Iterable[str]] = None,
        **kwargs,
    ):
        self.path = path
        self.endpoint = endpoint
        self.host = host
        self.methods = methods
        self.kwargs = kwargs

    def get_rules(self, map: Map) -> t.Iterable[Rule]:
        host = self.host

        if host is None and map.host_matching:
            # this creates a "match any" rule, and will put the value of the host
            # into the variable "__host__"
            host = "<__host__>"

        # the typing for endpoint is a str, but the doc states it can be any value,
        # however then the redirection URL building will not work
        rule = Rule(
            self.path, endpoint=self.endpoint, methods=self.methods, host=host, **self.kwargs
        )
        yield rule


class _EndpointFunction(RuleFactory):
    """
    Internal rule factory that generates router Rules from ``@route`` annotated functions, or anything else
    that can be interpreted as a ``_RouteEndpoint``. It extracts the rule attributes from the
    ``_RuleAttributes`` attribute defined by ``_RouteEndpoint``. Example::

        @route("/my_api", methods=["GET"])
        def do_get(request: Request, _args):
            # should be inherited
            return Response(f"{request.path}/do-get")

        router.add(do_get)  # <- will use an _EndpointFunction RuleFactory.
    """

    def __init__(self, fn: _RouteEndpoint):
        self.fn = fn

    def get_rules(self, map: Map) -> t.Iterable[Rule]:
        attrs: list[_RuleAttributes] = self.fn.rule_attributes
        for attr in attrs:
            yield from _EndpointRule(
                path=attr.path,
                endpoint=self.fn,
                host=attr.host,
                methods=attr.methods,
                **attr.kwargs,
            ).get_rules(map)


class _EndpointsObject(RuleFactory):
    """
    Scans the given object for members that can be used as a `RouteEndpoint` and yields them as rules.
    """

    def __init__(self, obj: object):
        self.obj = obj

    def get_rules(self, map: Map) -> t.Iterable[Rule]:
        endpoints: list[_RouteEndpoint] = []

        members = inspect.getmembers(self.obj)
        for _, member in members:
            if hasattr(member, "rule_attributes"):
                endpoints.append(member)

        # make sure rules with "HEAD" are added first, otherwise werkzeug would let any "GET" rule would overwrite them.
        for endpoint in endpoints:
            for attr in endpoint.rule_attributes:
                if attr.methods and "HEAD" in attr.methods:
                    yield from _EndpointRule(
                        path=attr.path,
                        endpoint=endpoint,
                        host=attr.host,
                        methods=attr.methods,
                        **attr.kwargs,
                    ).get_rules(map)

        for endpoint in endpoints:
            for attr in endpoint.rule_attributes:
                if not attr.methods or "HEAD" not in attr.methods:
                    yield from _EndpointRule(
                        path=attr.path,
                        endpoint=endpoint,
                        host=attr.host,
                        methods=attr.methods,
                        **attr.kwargs,
                    ).get_rules(map)
