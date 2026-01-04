import argparse
import json
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

RATE_LIMIT_STATE = {"count": 0}
FIXTURE_DIR = Path("scripts/proofs/_fixtures")
PDF_FIXTURE = FIXTURE_DIR / "sample.pdf"
LONG_HTML_SENTENCE = (
    "Deterministic fixture text for extraction quality checks. Orion Analytics builds secure telemetry platforms "
    "for spacecraft, while Harbor Navigation automates port logistics with resilient APIs. Each release ships "
    "with observability, rate limits, and typed contracts for safety-critical integrations."
)
LONG_HTML_BODY = " ".join([LONG_HTML_SENTENCE for _ in range(40)])


class FixtureHandler(BaseHTTPRequestHandler):
    server_version = "Phase4_13Fixture/1.0"

    def do_GET(self) -> None:  # noqa: N802
        path = self.path.split("?", 1)[0]

        if path == "/final":
            self._write(200, {"Content-Type": "text/html"}, b"<html><body>FINAL</body></html>")
            return

        if path == "/redirect1":
            self._write(302, {"Location": "/redirect2"}, b"")
            return

        if path == "/redirect2":
            self._write(302, {"Location": "/final"}, b"")
            return

        if path == "/png":
            png_bytes = (
                b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
                b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc``\x00\x00\x00\x02\x00\x01"
                b"\xe2!\xbc3\x00\x00\x00\x00IEND\xaeB`\x82"
            )
            self._write(200, {"Content-Type": "image/png"}, png_bytes)
            return

        if path == "/big":
            body = b"<html><body>" + (b"X" * 2_100_000) + b"</body></html>"
            self._write(200, {"Content-Type": "text/html"}, body)
            return

        if path == "/robots.txt":
            rules = "User-agent: *\nDisallow: /blocked\n"
            self._write(200, {"Content-Type": "text/plain"}, rules.encode("utf-8"))
            return

        if path == "/blocked":
            self._write(200, {"Content-Type": "text/html"}, b"<html><body>blocked</body></html>")
            return

        if path == "/html_etag":
            etag = '"v1"'
            last_modified = "Wed, 01 Jan 2025 00:00:00 GMT"
            inm = self.headers.get("If-None-Match")
            if inm and inm.strip() == etag:
                self._write(304, {"ETag": etag, "Last-Modified": last_modified}, b"")
                return
            body = b"<html><body>etag fresh</body></html>"
            headers = {"Content-Type": "text/html", "ETag": etag, "Last-Modified": last_modified}
            self._write(200, headers, body)
            return

        if path == "/rate_limited":
            RATE_LIMIT_STATE["count"] += 1
            if RATE_LIMIT_STATE["count"] == 1:
                self._write(429, {"Retry-After": "1", "Content-Type": "text/plain"}, b"retry later")
                return
            self._write(200, {"Content-Type": "text/html"}, b"<html><body>rate ok</body></html>")
            return

        if path == "/content_html":
            body = f"<html><head><title>Fixture Content</title></head><body><h1>Fixture Content</h1><p>{LONG_HTML_BODY}</p></body></html>".encode("utf-8")
            self._write(200, {"Content-Type": "text/html"}, body)
            return

        if path == "/content_html_variant":
            variant_tail = " Variant marker B to force a different hash while keeping the template signature stable."
            body = (
                f"<html><head><title>Fixture Content</title></head><body>"
                f"<h1>Fixture Content</h1><p>{LONG_HTML_BODY}{variant_tail}</p></body></html>"
            ).encode("utf-8")
            self._write(200, {"Content-Type": "text/html"}, body)
            return

        if path == "/thin_html":
            body = b"<html><body><p>Hi</p></body></html>"
            self._write(200, {"Content-Type": "text/html"}, body)
            return

        if path == "/login_html":
            body = b"<html><head><title>Sign in Required</title></head><body>Please sign in or subscribe to continue.</body></html>"
            self._write(200, {"Content-Type": "text/html"}, body)
            return

        if path == "/pdf":
            if PDF_FIXTURE.exists():
                self._write(200, {"Content-Type": "application/pdf"}, PDF_FIXTURE.read_bytes())
            else:
                self._write(500, {"Content-Type": "text/plain"}, b"pdf fixture missing")
            return

        self._write(404, {"Content-Type": "application/json"}, json.dumps({"error": "not found"}).encode("utf-8"))

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A003
        return

    def _write(self, status: int, headers: dict[str, str], body: bytes) -> None:
        payload = body or b""
        self.send_response(status)
        for key, value in headers.items():
            self.send_header(key, value)
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        if payload:
            self.wfile.write(payload)


def find_free_server(host: str) -> ThreadingHTTPServer:
    server = ThreadingHTTPServer((host, 0), FixtureHandler)
    return server


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Phase 4.13 deterministic local HTTP server")
    parser.add_argument("--host", default="127.0.0.1", help="Host to bind")
    args = parser.parse_args(argv)

    server = find_free_server(args.host)
    host, port = server.server_address
    base_url = f"http://{host}:{port}"
    print(f"base_url={base_url}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("shutting down", file=sys.stderr)
    finally:
        server.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
