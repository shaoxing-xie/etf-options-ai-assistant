from __future__ import annotations

import json
import os
import sys
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from apps.chart_console.api.routes import ApiRoutes
from apps.chart_console.api.serializers import sanitize
from apps.chart_console.api.services import ApiServices


def _normalize_request_path(path: str) -> str:
    """Collapse duplicate slashes and strip a trailing slash so routing matches common URL variants."""
    p = path or "/"
    while "//" in p:
        p = p.replace("//", "/")
    if len(p) > 1 and p.endswith("/"):
        p = p.rstrip("/")
    return p


class ChartApiHandler(BaseHTTPRequestHandler):
    frontend_dir = Path(__file__).resolve().parents[1] / "frontend"
    routes = ApiRoutes(ApiServices())

    def _send_json(self, data: dict, status: int = 200, headers: dict[str, str] | None = None) -> None:
        payload = json.dumps(sanitize(data), ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        for k, v in (headers or {}).items():
            self.send_header(str(k), str(v))
        self.end_headers()
        self.wfile.write(payload)

    def _read_json(self) -> dict:
        length = int(self.headers.get("Content-Length", "0") or "0")
        if length <= 0:
            return {}
        raw = self.rfile.read(length)
        try:
            obj = json.loads(raw.decode("utf-8"))
            return obj if isinstance(obj, dict) else {}
        except Exception:
            return {}

    def _serve_static(self, path: str) -> None:
        if path in ("/", ""):
            target = self.frontend_dir / "index.html"
        else:
            target = (self.frontend_dir / path.lstrip("/")).resolve()
            if not str(target).startswith(str(self.frontend_dir.resolve())):
                self.send_error(HTTPStatus.FORBIDDEN, "forbidden")
                return
        if not target.exists() or not target.is_file():
            self.send_error(HTTPStatus.NOT_FOUND, "not found")
            return
        content_type = "text/plain; charset=utf-8"
        if target.suffix == ".html":
            content_type = "text/html; charset=utf-8"
        elif target.suffix == ".js":
            content_type = "application/javascript; charset=utf-8"
        elif target.suffix == ".css":
            content_type = "text/css; charset=utf-8"
        body = target.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        path = _normalize_request_path(parsed.path)
        query = parse_qs(parsed.query)
        if path.startswith("/api/"):
            out = self.routes.handle_get(path, query)
            if isinstance(out, tuple) and len(out) == 3:
                payload, code, headers = out
            else:
                payload, code = out
                headers = {}
            self._send_json(payload, status=code, headers=headers)
            return
        self._serve_static(path)

    def do_HEAD(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        path = _normalize_request_path(parsed.path)
        query = parse_qs(parsed.query)
        if path.startswith("/api/"):
            out = self.routes.handle_get(path, query)
            if isinstance(out, tuple) and len(out) == 3:
                payload, code, headers = out
            else:
                payload, code = out
                headers = {}
            body = json.dumps(sanitize(payload), ensure_ascii=False).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            for k, v in (headers or {}).items():
                self.send_header(str(k), str(v))
            self.end_headers()
            return

        if path in ("/", ""):
            target = self.frontend_dir / "index.html"
        else:
            target = (self.frontend_dir / path.lstrip("/")).resolve()
            if not str(target).startswith(str(self.frontend_dir.resolve())):
                self.send_error(HTTPStatus.FORBIDDEN, "forbidden")
                return
        if not target.exists() or not target.is_file():
            self.send_error(HTTPStatus.NOT_FOUND, "not found")
            return
        content_type = "text/plain; charset=utf-8"
        if target.suffix == ".html":
            content_type = "text/html; charset=utf-8"
        elif target.suffix == ".js":
            content_type = "application/javascript; charset=utf-8"
        elif target.suffix == ".css":
            content_type = "text/css; charset=utf-8"
        size = target.stat().st_size
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(size))
        self.end_headers()

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        path = _normalize_request_path(parsed.path)
        body = self._read_json()
        if path.startswith("/api/"):
            payload, code = self.routes.handle_post(path, body)
            self._send_json(payload, status=code)
            return
        self._send_json({"success": False, "message": "not found"}, status=404)


def run_server(host: str = "0.0.0.0", port: int = 8611) -> None:
    server = ThreadingHTTPServer((host, port), ChartApiHandler)
    print(f"[chart_console_pro] URL=http://{host}:{port}")
    server.serve_forever()


if __name__ == "__main__":
    run_server(
        host=os.environ.get("CHART_CONSOLE_PRO_HOST", "0.0.0.0"),
        port=int(os.environ.get("CHART_CONSOLE_PRO_PORT", "8611")),
    )
