import abc
from urllib.parse import urlparse

import requests
import urllib3.util
from werkzeug import Request, Response
from werkzeug.datastructures import Headers

from .request import get_raw_base_url, get_raw_current_url, get_raw_path, restore_payload


class HttpClient(abc.ABC):
    """
    An HTTP client that can make http requests using werkzeug's request object.
    """

    @abc.abstractmethod
    def request(self, request: Request, server: str | None = None) -> Response:
        """
        Make the given HTTP as a client.

        :param request: the request to make
        :param server: the URL to send the request to, which defaults to the host component of the original Request.
        :return: the response.
        """
        raise NotImplementedError

    @abc.abstractmethod
    def close(self):
        """
        Close any underlying resources the client may need.
        """
        pass

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


class _VerifyRespectingSession(requests.Session):
    """
    A class which wraps requests.Session to circumvent https://github.com/psf/requests/issues/3829.
    This ensures that if `REQUESTS_CA_BUNDLE` or `CURL_CA_BUNDLE` are set, the request does not perform the TLS
    verification if `session.verify` is set to `False.
    """

    def merge_environment_settings(self, url, proxies, stream, verify, *args, **kwargs):
        if self.verify is False:
            verify = False

        return super(_VerifyRespectingSession, self).merge_environment_settings(
            url, proxies, stream, verify, *args, **kwargs
        )


class SimpleRequestsClient(HttpClient):
    session: requests.Session
    follow_redirects: bool

    def __init__(self, session: requests.Session = None, follow_redirects: bool = True):
        self.session = session or _VerifyRespectingSession()
        self.follow_redirects = follow_redirects

    @staticmethod
    def _get_destination_url(request: Request, server: str | None = None) -> str:
        if server:
            # accepts "http://localhost:5000" or "localhost:5000"
            if "://" in server:
                parts = urlparse(server)
                scheme, server = parts.scheme, parts.netloc
            else:
                scheme = request.scheme
            return get_raw_current_url(scheme, server, request.root_path, get_raw_path(request))

        return get_raw_base_url(request)

    @staticmethod
    def _transform_response_headers(response: requests.Response) -> Headers:
        """
        `requests` by default concatenate headers in response under a single header separated by a comma
        This behavior is generally the same as having the same header multiple times with different values in a
        response.
        However, specific headers like `Set-Cookie` needs to be defined multiple times. By directly using the raw
        `urllib3` response that still contains non-concatenate values, we can follow more closely the response.
        """
        headers = Headers()
        for k, v in response.raw.headers.iteritems():
            headers.add(k, v)
        return headers

    def request(self, request: Request, server: str | None = None) -> Response:
        """
        Very naive implementation to make the given HTTP request using the requests library, i.e., process the request
        as a client.

        :param request: the request to perform
        :param server: the URL to send the request to, which defaults to the host component of the original Request.
        :param allow_redirects: allow the request to follow redirects
        :return: the response.
        """

        url = self._get_destination_url(request, server)

        headers = dict(request.headers.items())

        # urllib3 (used by requests) will set an Accept-Encoding header ("gzip,deflate")
        # - See urllib3.util.request.ACCEPT_ENCODING
        # - The solution to this, provided by urllib3, is to use `urllib3.util.SKIP_HEADER`
        #   to prevent the header from being added.
        if not request.headers.get("accept-encoding"):
            headers["accept-encoding"] = urllib3.util.SKIP_HEADER

        response = self.session.request(
            method=request.method,
            # use raw base url to preserve path url encoding
            url=url,
            # request.args are only the url parameters
            params=list(request.args.items(multi=True)),
            headers=headers,
            data=restore_payload(request),
            stream=True,
            allow_redirects=self.follow_redirects,
        )

        if request.method == "HEAD":
            # for HEAD  requests we have to keep the original content-length, but it will be re-calculated when creating
            # the final_response object
            final_response = Response(
                response=response.content,
                status=response.status_code,
                headers=self._transform_response_headers(response),
            )
            final_response.content_length = response.headers.get("Content-Length", 0)
            return final_response

        response_headers = self._transform_response_headers(response)

        if "chunked" in (transfer_encoding := response_headers.get("Transfer-Encoding", "")):
            response_headers.pop("Content-Length", None)
            # We should not set `Transfer-Encoding` in a Response, because it is the responsibility of the webserver
            # to do so, if there are no Content-Length. However, gzip behavior is more related to the actual content of
            # the response, so we keep that one.
            transfer_encoding_values = [v.strip() for v in transfer_encoding.split(",")]
            transfer_encoding_no_chunked = [
                v for v in transfer_encoding_values if v.lower() != "chunked"
            ]
            response_headers.setlist("Transfer-Encoding", transfer_encoding_no_chunked)

        final_response = Response(
            response=(chunk for chunk in response.raw.stream(1024, decode_content=False)),
            status=response.status_code,
            headers=response_headers,
        )

        return final_response

    def close(self):
        self.session.close()


def make_request(request: Request) -> Response:
    """
    Convenience method to make the given HTTP as a client.

    :param request: the request to make
    :return: the response.
    """
    with SimpleRequestsClient() as client:
        return client.request(request)
