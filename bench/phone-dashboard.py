"""Serve the built dashboard only to the test phone and local interface."""
import argparse
import ipaddress
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import URLError
from urllib.parse import urlsplit
from urllib.request import urlopen

parser = argparse.ArgumentParser()
parser.add_argument("listen", type=ipaddress.IPv4Address)
parser.add_argument("phone", type=ipaddress.IPv4Address)
args = parser.parse_args()
root = Path(__file__).resolve().parent / "vite-build-radio"
if not (root / "index.html").is_file():
    parser.error("Dashboard build missing")


class DashboardHandler(SimpleHTTPRequestHandler):
    def client_allowed(self):
        return self.client_address[0] in {str(args.phone), str(args.listen)}

    def do_GET(self):
        if urlsplit(self.path).path != "/api/radio-link":
            return super().do_GET()
        if not self.client_allowed():
            self.send_error(403)
            return
        try:
            with urlopen("http://127.0.0.1:8000/api/radio-link", timeout=4) as upstream:
                payload = upstream.read()
        except (URLError, TimeoutError):
            self.send_error(502, "Radio statistics unavailable")
            return
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def list_directory(self, path):
        self.send_error(404)

    def send_head(self):
        if not self.client_allowed():
            self.send_error(403)
            return None
        if urlsplit(self.path).path in {"/multicam", "/science", "/controller", "/settings"}:
            self.path = "/index.html"
        return super().send_head()


with ThreadingHTTPServer((str(args.listen), 5174), partial(DashboardHandler, directory=root)) as server:
    server.serve_forever()
