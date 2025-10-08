# api/oauth/callback.py
import os, json, requests
from urllib.parse import urlparse, parse_qs
from http.server import BaseHTTPRequestHandler

REDIS_URL = os.getenv("UPSTASH_REDIS_REST_URL")
REDIS_TOKEN = os.getenv("UPSTASH_REDIS_REST_TOKEN")
CLIENT_ID = os.getenv("LINKEDIN_CLIENT_ID", "")
CLIENT_SECRET = os.getenv("LINKEDIN_CLIENT_SECRET", "")
REDIRECT_URI = os.getenv("LINKEDIN_REDIRECT_URI", "")

def _h(): return {"Authorization": f"Bearer {REDIS_TOKEN}"} if REDIS_TOKEN else {}
def rget(k):
    if not REDIS_URL or not REDIS_TOKEN: return None
    try: return requests.get(f"{REDIS_URL}/get/{k}", headers=_h(), timeout=8).json().get("result")
    except: return None
def rset(k,v):
    if not REDIS_URL or not REDIS_TOKEN: return
    try: requests.get(f"{REDIS_URL}/set/{k}/{v}", headers=_h(), timeout=8)
    except: pass
def rsetex(k,s,v):
    if not REDIS_URL or not REDIS_TOKEN: return
    try: requests.get(f"{REDIS_URL}/setex/{k}/{s}/{v}", headers=_h(), timeout=8)
    except: pass
def rdel(k):
    if not REDIS_URL or not REDIS_TOKEN: return
    try: requests.get(f"{REDIS_URL}/del/{k}", headers=_h(), timeout=8)
    except: pass

def respond(h, code, data):
    h.send_response(code); h.send_header("Content-Type","application/json; charset=utf-8"); h.end_headers()
    h.wfile.write(json.dumps(data).encode("utf-8"))

class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        qs = parse_qs(urlparse(self.path).query)
        code = (qs.get("code") or [""])[0]
        state = (qs.get("state") or [""])[0]
        if not code or not state:
            return respond(self, 400, {"ok": False, "error": "missing code/state"})
        if not rget(f"li:oauth:state:{state}"):
            return respond(self, 400, {"ok": False, "error": "invalid or expired state"})
        uid = state.split(":",1)[0]

        token_res = requests.post("https://www.linkedin.com/oauth/v2/accessToken", data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": REDIRECT_URI,
            "client_id": CLIENT_ID,
            "client_secret": CLIENT_SECRET
        }, timeout=15)
        if token_res.status_code >= 400:
            return respond(self, token_res.status_code, {"ok": False, "error": token_res.text})
        token = token_res.json()
        access = token.get("access_token")
        expires = int(token.get("expires_in", 0))
        refresh = token.get("refresh_token") or ""
        refresh_expires = int(token.get("refresh_token_expires_in", 0))
        if not access:
            return respond(self, 400, {"ok": False, "error": "no access_token"})

        me = requests.get("https://api.linkedin.com/v2/me",
                          headers={"Authorization": f"Bearer {access}"}, timeout=10)
        if me.status_code >= 400:
            return respond(self, me.status_code, {"ok": False, "error": me.text})
        person_id = me.json().get("id")

        if expires: rsetex(f"li:{uid}:access", expires, access)
        else: rset(f"li:{uid}:access", access)
        if refresh: rset(f"li:{uid}:refresh", refresh)
        if refresh_expires: rsetex(f"li:{uid}:refresh_ttl", refresh_expires, "1")
        rset(f"li:{uid}:person", person_id or "")

        rdel(f"li:oauth:state:{state}")
        return respond(self, 200, {"ok": True, "user": uid, "person": person_id})
