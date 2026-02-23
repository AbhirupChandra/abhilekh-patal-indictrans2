"""
Simple proxy server that:
  1. Serves static HTML files from this directory
  2. Proxies /solr/* requests to the actual Solr instance (bypasses CORS)

Usage:
    python server.py
    Then open http://localhost:8082/abhilekh_search.html
"""

import http.server
import urllib.request
import urllib.error
import json
import os

SOLR_BASE = "http://10.16.40.75:8983/solr"
PORT = 8083
DIRECTORY = os.path.dirname(os.path.abspath(__file__))


class ProxyHandler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=DIRECTORY, **kwargs)

    def do_GET(self):
        # Proxy requests starting with /solr/ to the real Solr
        if self.path.startswith("/solr/"):
            self._proxy_to_solr()
        else:
            super().do_GET()

    def _proxy_to_solr(self):
        target_url = SOLR_BASE + self.path[len("/solr"):]  # strip leading /solr
        try:
            req = urllib.request.Request(target_url)
            with urllib.request.urlopen(req, timeout=15) as resp:
                body = resp.read()
                self.send_response(resp.status)
                self.send_header("Content-Type", resp.headers.get("Content-Type", "application/json"))
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                self.wfile.write(body)
        except urllib.error.HTTPError as e:
            body = e.read()
            self.send_response(e.code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(body)
        except Exception as e:
            error_msg = json.dumps({"error": str(e)}).encode()
            self.send_response(502)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(error_msg)

    def log_message(self, format, *args):
        # Color-coded logging
        path = args[0] if args else ""
        if "/solr/" in str(path):
            print(f"  [SOLR PROXY] {format % args}")
        else:
            print(f"  [STATIC]     {format % args}")


if __name__ == "__main__":
    server = http.server.HTTPServer(("", PORT), ProxyHandler)
    print(f"Server running at http://localhost:{PORT}")
    print(f"Solr proxy:  http://localhost:{PORT}/solr/... -> {SOLR_BASE}/...")
    print(f"Open:        http://localhost:{PORT}/abhilekh_search.html")
    print()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down.")
        server.server_close()
