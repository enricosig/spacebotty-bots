from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse

class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        # Forward the request internally to the real callback
        # by redirecting to /api/oauth/callback with the same query.
        qs = urlparse(self.path).query
        location = "/api/oauth/callback" + (f"?{qs}" if qs else "")
        # Use 307 to preserve method, but GET is fine with 302 as well.
        self.send_response(307)
        self.send_header("Location", location)
        self.end_headers()
