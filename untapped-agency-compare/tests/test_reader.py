"""Network boundary tests: all DNS, sockets, TLS and HTTP are mocked."""
from contextlib import contextmanager, ExitStack
import io
from pathlib import Path
import socket
import sys
import threading
import unittest
from unittest.mock import MagicMock, patch

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "server"))
import agency_server as server
from extract import MAX_BYTES
from mcp_stdio import ToolError


class Response:
    def __init__(self, body=b"<p>We offer website design.</p>", status=200, headers=None):
        self.body = io.BytesIO(body)
        self.status = status
        self.headers = {"Content-Type": "text/html; charset=utf-8", **(headers or {})}

    def getheader(self, key, default=None):
        return self.headers.get(key, default)

    def read1(self, size):
        return self.body.read(size)


@contextmanager
def network(responses, addresses=("8.8.8.8",)):
    connections = []
    for response in responses:
        connection = MagicMock()
        connection.getresponse.return_value = response
        connections.append(connection)
    with ExitStack() as stack:
        dns = stack.enter_context(patch.object(socket, "getaddrinfo", return_value=[
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", (a, 443)) for a in addresses]))
        tcp = stack.enter_context(patch.object(socket, "create_connection", return_value=MagicMock()))
        tls = stack.enter_context(patch.object(server.ssl, "create_default_context"))
        http = stack.enter_context(patch.object(server.http.client, "HTTPSConnection", side_effect=connections))
        yield connections, dns, tcp, tls, http


class ReaderTests(unittest.TestCase):
    def test_reads_only_requested_page_with_pinned_address_and_tls_name(self):
        with network([Response()]) as (connections, dns, tcp, tls, http):
            result = server.read_agency_page(url="https://agency.example/offer?a=1#section")
            self.assertEqual(result["page_text"], "We offer website design.")
            self.assertEqual(result["source_url"], "https://agency.example/offer?a=1#section")
            self.assertEqual(dns.call_count, 1)
            self.assertEqual(tcp.call_args.args[0], ("8.8.8.8", 443))
            self.assertLessEqual(tcp.call_args.kwargs["timeout"], 20)
            self.assertEqual(tls.return_value.wrap_socket.call_args.kwargs["server_hostname"], "agency.example")
            self.assertEqual(connections[0].request.call_args.args[:2], ("GET", "/offer?a=1"))
            self.assertEqual(connections[0].request.call_args.kwargs["headers"]["Accept-Encoding"], "identity")
            connections[0].close.assert_called_once()

    def test_paste_never_touches_network(self):
        with patch.object(socket, "getaddrinfo", side_effect=AssertionError("offline")):
            result = server.read_agency_page(text="<p>Services: design.</p>", source_url="https://agency.example/")
            self.assertEqual(result["page_text"], "Services: design.")
            self.assertEqual(result["input"], "pasted")

    def test_paste_without_url_is_explicitly_unsourced(self):
        result = server.read_agency_page(text="Services: design.")
        self.assertEqual(result["source_url"], "")

    def test_exactly_one_input(self):
        for args in ({}, {"url": "https://a.example", "text": "x"}, {"text": 12},
                     {"url": "https://a.example", "source_url": "https://b.example"}):
            with self.subTest(args=args), self.assertRaises(ValueError):
                server.read_agency_page(**args)

    def test_disallowed_url_forms_before_dns(self):
        with patch.object(socket, "getaddrinfo", side_effect=AssertionError("must reject before DNS")):
            for url in ("http://a.example", "file:///tmp/x", "https://user:pass@a.example", "https://a.example:444",
                        "https://a.example/\r\nCookie:x", "https:///empty", "https://a.example:bad", 7):
                with self.subTest(url=url), self.assertRaises(ValueError):
                    server.read_agency_page(url=url)

    def test_private_and_mixed_dns_answers_rejected(self):
        for addresses in (("127.0.0.1",), ("::1",), ("169.254.169.254",), ("10.0.0.1",), ("8.8.8.8", "192.168.1.1")):
            with self.subTest(addresses=addresses), network([], addresses) as (_, _, tcp, _, _):
                with self.assertRaisesRegex(ValueError, "public"):
                    server.read_agency_page(url="https://a.example")
                tcp.assert_not_called()

    def test_three_same_host_redirects_allowed(self):
        responses = [Response(status=302, headers={"Location": "/step" + str(n)}) for n in range(3)] + [Response()]
        with network(responses) as (connections, dns, _, _, _):
            result = server.read_agency_page(url="https://a.example/start")
            self.assertEqual(result["redirects"], 3)
            self.assertEqual(result["source_url"], "https://a.example/step2")
            self.assertEqual(dns.call_count, 4)
            for connection in connections:
                connection.close.assert_called_once()

    def test_fourth_redirect_rejected(self):
        with network([Response(status=302, headers={"Location": "/again"}) for _ in range(4)]):
            with self.assertRaisesRegex(ValueError, "three redirects"):
                server.read_agency_page(url="https://a.example")

    def test_off_host_or_downgrade_redirect_never_requested(self):
        for location in ("https://b.example/", "http://a.example/", "//b.example/x", "https://a.example:444/x"):
            with self.subTest(location=location), network([Response(status=301, headers={"Location": location})]) as (_, dns, _, _, http):
                with self.assertRaises(ValueError):
                    server.read_agency_page(url="https://a.example/")
                self.assertEqual(http.call_count, 1)
                self.assertEqual(dns.call_count, 1)

    def test_redirect_without_location_rejected(self):
        with network([Response(status=302)]), self.assertRaises(ValueError):
            server.read_agency_page(url="https://a.example")

    def test_http_failures_explicit(self):
        with network([Response(status=404)]), self.assertRaisesRegex(ValueError, "404"):
            server.read_agency_page(url="https://a.example")

    def test_header_size_limit(self):
        with network([Response(headers={"Content-Length": str(MAX_BYTES + 1)})]), self.assertRaisesRegex(ValueError, "2 MiB"):
            server.read_agency_page(url="https://a.example")

    def test_stream_size_limit_without_content_length(self):
        with network([Response(b"x" * (MAX_BYTES + 1))]), self.assertRaisesRegex(ValueError, "2 MiB"):
            server.read_agency_page(url="https://a.example")

    def test_exact_limit_allowed(self):
        with network([Response(b"x" * MAX_BYTES)]):
            result = server.read_agency_page(url="https://a.example")
            self.assertEqual(len(result["page_text"]), MAX_BYTES)

    def test_paste_size_limit(self):
        with self.assertRaises(ValueError):
            server.read_agency_page(text="x" * (MAX_BYTES + 1))

    def test_binary_and_compression_rejected(self):
        for headers in ({"Content-Type": "application/pdf"}, {"Content-Encoding": "gzip"}):
            with self.subTest(headers=headers), network([Response(headers=headers)]), self.assertRaises(ValueError):
                server.read_agency_page(url="https://a.example")

    def test_charset_and_hidden_content(self):
        body = '<script>Services: fabricated</script><p>Services: café design.</p>'.encode("latin-1")
        with network([Response(body, headers={"Content-Type": "text/html; charset=iso-8859-1"})]):
            result = server.read_agency_page(url="https://a.example")
            self.assertEqual(result["page_text"], "Services: café design.")

    def test_dns_resolver_respects_tool_deadline(self):
        release = threading.Event()
        def held(*args, **kwargs):
            release.wait(1)
            return []
        try:
            with patch.object(server, "TIMEOUT", .01), patch.object(socket, "getaddrinfo", side_effect=held):
                with self.assertRaisesRegex(ValueError, "timeout"):
                    server.read_agency_page(url="https://a.example")
        finally:
            release.set()

    def test_timeout_error_is_safe_tool_error(self):
        with patch.object(socket, "getaddrinfo", side_effect=socket.gaierror("sensitive system detail")):
            with self.assertRaises(ToolError) as caught:
                server.call("read_agency_page", {"url": "https://a.example"})
            self.assertNotIn("sensitive", str(caught.exception))

    def test_tool_validation_rejects_unknown_fields(self):
        for name, args in (("criteria", {"unexpected": True}), ("compare", {}), ("no_tool", {})):
            with self.assertRaises(ToolError):
                server.call(name, args)


if __name__ == "__main__":
    unittest.main()
