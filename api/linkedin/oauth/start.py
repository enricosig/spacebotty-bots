from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse, urlunparse

class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        # Preserve the original query string (?uid=...)
        qs = urlparse(self.path).query
        location = "/api/oauth/start" + (f"?{qs}" if qs else "")
        self.send_response(302)
        self.send_header("Location", location)
        self.end_headers()
