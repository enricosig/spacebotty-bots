# api/diag.py
from http.server import BaseHTTPRequestHandler
import os, json

WHITELIST = [
    "PUBLIC_BASE_URL",
    "TELEGRAM_BOT_TOKEN",
    "OPENAI_API_KEY",
    "OPENAI_MODEL",
    "UPSTASH_REDIS_REST_URL",
    "UPSTASH_REDIS_REST_TOKEN",
    "LINKEDIN_CLIENT_ID",
    "LINKEDIN_REDIRECT_URI"
]

def mask(v, keep=4):
    if not v: return None
    return v[:keep] + "..." if len(v) > keep else v

class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        env = {k: mask(os.getenv(k)) for k in WHITELIST}
        body = json.dumps({"ok": True, "env": env}).encode("utf-8")
        self.send_response(200); self.send_header("Content-Type","application/json"); self.end_headers()
        self.wfile.write(body)
