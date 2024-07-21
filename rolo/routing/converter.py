import typing as t

from werkzeug.routing import BaseConverter, Map


class RegexConverter(BaseConverter):
    """
    A converter that can be used to inject a regex as parameter, e.g., ``path=/<regex('[a-z]+'):my_var>``.
    When using groups in regex, make sure they are non-capturing ``(?:[a-z]+)``
    """

    def __init__(self, map: Map, *args: t.Any, **kwargs: t.Any) -> None:
        super().__init__(map, *args, **kwargs)
        self.regex = args[0]


class PortConverter(BaseConverter):
    """
    Useful to optionally match ports for host patterns, like ``localstack.localhost.cloud<port:port>``. Notice how you
    don't need to specify the colon. The regex matches it if the port is there, and will remove the colon if matched.
    The converter converts the port to an int, or returns None if there's no port in the input string.
    """

    regex = r"(?::[0-9]{1,5})?"

    def to_python(self, value: str) -> t.Any:
        if value:
            return int(value[1:])
        return None
