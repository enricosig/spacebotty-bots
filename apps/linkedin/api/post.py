# apps/linkedin/api/post.py
import os, json, requests
from urllib.parse import urlparse, parse_qs, unquote_plus
from http.server import BaseHTTPRequestHandler

REDIS_URL = os.getenv("UPSTASH_REDIS_REST_URL")
REDIS_TOKEN = os.getenv("UPSTASH_REDIS_REST_TOKEN")
CLIENT_ID = os.getenv("LINKEDIN_CLIENT_ID", "")
CLIENT_SECRET = os.getenv("LINKEDIN_CLIENT_SECRET", "")

def _h(): return {"Authorization": f"Bearer {REDIS_TOKEN}"} if REDIS_TOKEN else {}
def rget(k):
    if not REDIS_URL or not REDIS_TOKEN: return None
    try: return requests.get(f"{REDIS_URL}/get/{k}", headers=_h(), timeout=8).json().get("result")
    except: return None
def rsetex(k,s,v):
    if not REDIS_URL or not REDIS_TOKEN: return
    try: requests.get(f"{REDIS_URL}/setex/{k}/{s}/{v}", headers=_h(), timeout=8)
    except: pass
def rset(k,v):
    if not REDIS_URL or not REDIS_TOKEN: return
    try: requests.get(f"{REDIS_URL}/set/{k}/{v}", headers=_h(), timeout=8)
    except: pass

def refresh_access(uid, refresh_token):
    try:
        tr = requests.post("https://www.linkedin.com/oauth/v2/accessToken", data={
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": CLIENT_ID,
            "client_secret": CLIENT_SECRET
        }, timeout=15)
        if tr.status_code >= 400: return None, None
        js = tr.json()
        access = js.get("access_token"); expires = int(js.get("expires_in", 0))
        if access:
            if expires: rsetex(f"li:{uid}:access", expires, access)
            else: rset(f"li:{uid}:access", access)
            return access, expires
    except: pass
    return None, None

def ensure_access(uid):
    access = rget(f"li:{uid}:access")
    if access: return access
    refresh = rget(f"li:{uid}:refresh")
    if refresh:
        access, _ = refresh_access(uid, refresh)
        if access: return access
    return None

def respond(h, code, data):
    h.send_response(code); h.send_header("Content-Type","application/json; charset=utf-8"); h.end_headers()
    h.wfile.write(json.dumps(data).encode("utf-8"))

class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        qs = parse_qs(urlparse(self.path).query)
        uid = (qs.get("uid") or [""])[0]
        text = unquote_plus((qs.get("text") or [""])[0]).strip()

        if not uid or not text:
            return respond(self, 400, {"ok": False, "error": "missing uid or text"})

        access = ensure_access(uid)
        person = rget(f"li:{uid}:person")
        if not access or not person:
            return respond(self, 401, {"ok": False, "error": "LinkedIn not connected for this user"})

        payload = {
            "author": f"urn:li:person:{person}",
            "lifecycleState": "PUBLISHED",
            "specificContent": {
                "com.linkedin.ugc.ShareContent": {
                    "shareCommentary": {"text": text},
                    "shareMediaCategory": "NONE"
                }
            },
            "visibility": {"com.linkedin.ugc.MemberNetworkVisibility": "PUBLIC"}
        }

        r = requests.post("https://api.linkedin.com/v2/ugcPosts",
                          headers={
                              "Authorization": f"Bearer {access}",
                              "X-Restli-Protocol-Version": "2.0.0",
                              "Content-Type": "application/json"
                          },
                          json=payload, timeout=20)

        if r.status_code >= 400:
            try: err = r.json()
            except: err = {"error": r.text}
            return respond(self, r.status_code, {"ok": False, "error": err})
        return respond(self, 200, {"ok": True, "result": r.json()})

    def do_POST(self):
        length = int(self.headers.get("content-length","0") or 0)
        if length == 0:
            return respond(self, 400, {"ok": False, "error": "Missing body"})
        try:
            body = json.loads(self.rfile.read(length).decode("utf-8"))
            uid = (body.get("uid") or "").strip()
            text = (body.get("text") or "").strip()
        except Exception:
            return respond(self, 400, {"ok": False, "error": "Invalid JSON"})
        if not uid or not text:
            return respond(self, 400, {"ok": False, "error": "missing uid/text"})
        return self.do_GET()
