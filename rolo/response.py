import json
import mimetypes
import typing as t
from importlib import resources

from werkzeug.exceptions import NotFound
from werkzeug.wrappers import Response as WerkzeugResponse

if t.TYPE_CHECKING:
    from types import ModuleType


class _StreamIterableWrapper(t.Iterable[bytes]):
    """
    This can wrap an IO[bytes] stream to return an Iterable with a default chunk size of 65536 bytes
    """

    def __init__(self, stream: t.IO[bytes], chunk_size: int = 65536):
        self.stream = stream
        self._chunk_size = chunk_size

    def __iter__(self) -> t.Iterator[bytes]:
        """
        When passing a stream back to the WSGI server, it will often iterate only 1 byte at a time. Using this chunking
        mechanism allows us to bypass this issue.
        The caller needs to call `close()` to properly close the file descriptor
        :return:
        """
        while data := self.stream.read(self._chunk_size):
            if not data:
                return b""

            yield data

    def close(self):
        if hasattr(self.stream, "close"):
            self.stream.close()


class Response(WerkzeugResponse):
    """
    An HTTP Response object, which simply extends werkzeug's Response object with a few convenience methods.
    """

    def update_from(self, other: WerkzeugResponse):
        """
        Updates this response object with the data from the given response object. It reads the status code,
        the response data, and updates its own headers (overwrites existing headers, but does not remove ones
        not present in the given object). Also updates ``call_on_close`` callbacks in the same way.

        :param other: the response object to read from
        """
        self.status_code = other.status_code
        self.response = other.response
        self._on_close.extend(other._on_close)
        self.headers.update(other.headers)

    def set_json(self, doc: t.Any, cls: t.Type[json.JSONEncoder] = None):
        """
        Serializes the given dictionary using localstack's ``CustomEncoder`` into a json response, and sets the
        mimetype automatically to ``application/json``.

        :param doc: the response dictionary to be serialized as JSON
        :param cls: the JSON encoder class to use for serializing the passed document
        """
        self.data = json.dumps(doc, cls=cls)
        self.mimetype = "application/json"

    def set_response(self, response: t.Union[str, bytes, bytearray, t.Iterable[bytes]]):
        """
        Function to set the low-level ``response`` object. This is copied from the werkzeug Response constructor. The
        response attribute always holds an iterable of bytes. Passing a str, bytes or bytearray is equivalent to
        calling ``response.data = <response>``. If None is passed, then it will create an empty list. If anything
        else is passed, the value is set directly. This value can be a list of bytes, and iterator that returns bytes
        (e.g., a generator), which can be used by the underlying server to stream responses to the client. Anything else
        (like passing dicts) will result in errors at lower levels of the server.

        :param response: the response value
        """
        if response is None:
            self.response = []
        elif isinstance(response, (str, bytes, bytearray)):
            self.data = response
        else:
            self.response = response

        return self

    def to_readonly_response_dict(self) -> t.Dict:
        """
        Returns a read-only version of a response dictionary as it is often expected by other libraries like boto.
        """
        return {
            "body": self.stream if self.is_streamed else self.data,
            "status_code": self.status_code,
            "headers": dict(self.headers),
        }

    @classmethod
    def for_json(cls, doc: t.Any, *args, **kwargs) -> "Response":
        """
        Creates a new JSON response from the given document. It automatically sets the mimetype to ``application/json``.

        :param doc: the document to serialize into JSON
        :param args: arguments passed to the ``Response`` constructor
        :param kwargs: keyword arguments passed to the ``Response`` constructor
        :return: a new Response object
        """
        response = cls(*args, **kwargs)
        response.set_json(doc)
        return response

    @classmethod
    def for_resource(cls, module: "ModuleType", path: str, *args, **kwargs) -> "Response":
        """
        Looks up the given file in the given module, and creates a new Response object with the contents of that
        file. It guesses the mimetype of the file and sets it in the response accordingly. If the file does not exist
        ,it raises a ``NotFound`` error.

        :param module: the module to look up the file in
        :param path: the path/file name
        :return: a new Response object
        """
        resource = resources.files(module).joinpath(path)
        if not resource.is_file():
            raise NotFound()
        mimetype = mimetypes.guess_type(resource.name)
        mimetype = mimetype[0] if mimetype and mimetype[0] else "application/octet-stream"

        return cls(_StreamIterableWrapper(resource.open("rb")), *args, mimetype=mimetype, **kwargs)
