# api/oauth/start.py
import os, requests, random, string
from urllib.parse import urlparse, parse_qs, urlencode
from http.server import BaseHTTPRequestHandler

REDIS_URL = os.getenv("UPSTASH_REDIS_REST_URL")
REDIS_TOKEN = os.getenv("UPSTASH_REDIS_REST_TOKEN")
CLIENT_ID = os.getenv("LINKEDIN_CLIENT_ID", "")
REDIRECT_URI = os.getenv("LINKEDIN_REDIRECT_URI", "")

SCOPES = "r_liteprofile w_member_social offline_access"

def _h(): 
    return {"Authorization": f"Bearer {REDIS_TOKEN}"} if REDIS_TOKEN else {}

def rsetex(k, s, v):
    if not REDIS_URL or not REDIS_TOKEN: 
        return
    try:
        requests.get(f"{REDIS_URL}/setex/{k}/{s}/{v}", headers=_h(), timeout=8)
    except Exception as e:
        print("rsetex err", repr(e), flush=True)

def _nonce(n=24): 
    return "".join(random.choices(string.ascii_letters + string.digits, k=n))

class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        qs = parse_qs(urlparse(self.path).query)
        uid = (qs.get("uid") or [""])[0]

        if not uid:
            self._json(400, {"ok": False, "error": "missing uid"})
            return
        if not CLIENT_ID or not REDIRECT_URI:
            # non reindirizzo alla callback: mostro un errore chiaro
            self._json(200, {
                "ok": False,
                "error": "Missing CLIENT_ID or REDIRECT_URI env on server",
                "hint": {
                    "LINKEDIN_CLIENT_ID": "set on Vercel",
                    "LINKEDIN_REDIRECT_URI": "https://spacebotty-bots.vercel.app/api/oauth/callback"
                }
            })
            return

        # Salvo uno state temporaneo per 10 minuti
        state = f"{uid}:{_nonce()}"
        rsetex(f"li:oauth:state:{state}", 600, "1")

        # Costruisco SEMPRE il redirect a LinkedIn
        auth_url = "https://www.linkedin.com/oauth/v2/authorization?" + urlencode({
            "response_type": "code",
            "client_id": CLIENT_ID,
            "redirect_uri": REDIRECT_URI,
            "scope": SCOPES,
            "state": state
        })

        self.send_response(302)
        self.send_header("Location", auth_url)
        self.end_headers()

    def _json(self, code, data):
        import json
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.end_headers()
        self.wfile.write(json.dumps(data).encode("utf-8"))
