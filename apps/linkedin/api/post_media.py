# apps/linkedin/api/post_media.py
import os, json, requests
from urllib.parse import urlparse, parse_qs, unquote_plus
from http.server import BaseHTTPRequestHandler

REDIS_URL = os.getenv("UPSTASH_REDIS_REST_URL")
REDIS_TOKEN = os.getenv("UPSTASH_REDIS_REST_TOKEN")
CLIENT_ID = os.getenv("LINKEDIN_CLIENT_ID", "")
CLIENT_SECRET = os.getenv("LINKEDIN_CLIENT_SECRET", "")

MAX_IMAGE_MB = int(os.getenv("MAX_IMAGE_MB", "10"))
REQ_TIMEOUT = int(os.getenv("REQ_TIMEOUT", "25"))

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

def respond(h, code, data):
    h.send_response(code); h.send_header("Content-Type","application/json; charset=utf-8"); h.end_headers()
    h.wfile.write(json.dumps(data).encode("utf-8"))

def ensure_access(uid):
    access = rget(f"li:{uid}:access")
    if access: return access
    refresh = rget(f"li:{uid}:refresh")
    if not refresh: return None
    try:
        tr = requests.post("https://www.linkedin.com/oauth/v2/accessToken", data={
            "grant_type": "refresh_token",
            "refresh_token": refresh,
            "client_id": CLIENT_ID,
            "client_secret": CLIENT_SECRET
        }, timeout=REQ_TIMEOUT)
        if tr.status_code >= 400: return None
        js = tr.json()
        access = js.get("access_token"); expires = int(js.get("expires_in", 0))
        if access:
            if expires: rsetex(f"li:{uid}:access", expires, access)
            else: rset(f"li:{uid}:access", access)
            return access
    except requests.Timeout:
        return None
    except: return None

def guess_content_type(url):
    l = url.lower()
    if l.endswith(".png"): return "image/png"
    if l.endswith(".webp"): return "image/webp"
    if l.endswith(".jpg") or l.endswith(".jpeg"): return "image/jpeg"
    return "image/jpeg"

def _safe_head(url):
    try:
        r = requests.head(url, timeout=REQ_TIMEOUT, allow_redirects=True)
        size = int(r.headers.get("Content-Length", "0") or 0)
        ctype = r.headers.get("Content-Type", "").lower()
        return size, ctype, None
    except requests.Timeout:
        return None, None, "timeout"
    except Exception as e:
        return None, None, repr(e)

def _download(url):
    try:
        r = requests.get(url, timeout=REQ_TIMEOUT)
        if r.status_code >= 400:
            return None, f"http {r.status_code}"
        return r.content, None
    except requests.Timeout:
        return None, "timeout"
    except Exception as e:
        return None, repr(e)

def _register(access, person_urn):
    payload = {
        "registerUploadRequest": {
            "owner": f"urn:li:person:{person_urn}",
            "recipes": ["urn:li:digitalmediaRecipe:feedshare-image"],
            "serviceRelationships": [{"identifier":"urn:li:userGeneratedContent","relationshipType":"OWNER"}],
            "supportedUploadMechanism": ["SYNCHRONOUS_UPLOAD"]
        }
    }
    r = requests.post("https://api.linkedin.com/v2/assets?action=registerUpload",
                      headers={"Authorization": f"Bearer {access}",
                               "X-Restli-Protocol-Version":"2.0.0",
                               "Content-Type":"application/json"},
                      json=payload, timeout=REQ_TIMEOUT)
    if r.status_code >= 400:
        try: return None, r.json()
        except: return None, {"error": r.text}
    data = r.json()
    upload_url = data["value"]["uploadMechanism"]["com.linkedin.digitalmedia.uploading.MediaUploadHttpRequest"]["uploadUrl"]
    asset = data["value"]["asset"]
    return (upload_url, asset), None

class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        qs = parse_qs(urlparse(self.path).query)
        uid = (qs.get("uid") or [""])[0]
        img_url = (qs.get("image_url") or [""])[0]
        text = unquote_plus((qs.get("text") or [""])[0]).strip()

        if not uid or not img_url or not text:
            return respond(self, 400, {"ok": False, "error": "missing uid/image_url/text"})

        access = ensure_access(uid); person = rget(f"li:{uid}:person")
        if not access or not person:
            return respond(self, 401, {"ok": False, "error": "LinkedIn not connected or token unavailable"})

        size, ctype, err = _safe_head(img_url)
        if err == "timeout": return respond(self, 408, {"ok": False, "error": "image HEAD timeout"})
        if size and size > MAX_IMAGE_MB * 1024 * 1024:
            return respond(self, 413, {"ok": False, "error": f"image too large (> {MAX_IMAGE_MB}MB)"})

        img_bytes, derr = _download(img_url)
        if derr == "timeout": return respond(self, 408, {"ok": False, "error": "image download timeout"})
        if derr: return respond(self, 400, {"ok": False, "error": f"image download failed: {derr}"})
        ctype = ctype or guess_content_type(img_url)

        reg, rerr = _register(access, person)
        if rerr: return respond(self, 400, {"ok": False, "error": rerr})
        upload_url, asset = reg

        r_up = requests.put(upload_url, data=img_bytes,
                            headers={"Content-Type": ctype}, timeout=REQ_TIMEOUT)
        if r_up.status_code not in (200,201,204):
            try: err = r_up.json()
            except: err = {"error": r_up.text}
            return respond(self, 400, {"ok": False, "error": {"upload": err}})

        payload = {
            "author": f"urn:li:person:{person}",
            "lifecycleState": "PUBLISHED",
            "specificContent": {
                "com.linkedin.ugc.ShareContent": {
                    "shareCommentary": {"text": text},
                    "shareMediaCategory": "IMAGE",
                    "media": [{"status": "READY", "media": asset}]
                }
            },
            "visibility": {"com.linkedin.ugc.MemberNetworkVisibility": "PUBLIC"}
        }

        r = requests.post("https://api.linkedin.com/v2/ugcPosts",
                          headers={"Authorization": f"Bearer {access}",
                                   "X-Restli-Protocol-Version":"2.0.0",
                                   "Content-Type":"application/json"},
                          json=payload, timeout=REQ_TIMEOUT)
        if r.status_code >= 400:
            try: err = r.json()
            except: err = {"error": r.text}
            return respond(self, r.status_code, {"ok": False, "error": err})
        return respond(self, 200, {"ok": True, "result": r.json()})

    def do_POST(self):
        length = int(self.headers.get("content-length","0") or 0)
        if length == 0: return respond(self, 400, {"ok": False, "error": "Missing body"})
        try:
            body = json.loads(self.rfile.read(length).decode("utf-8"))
            uid = (body.get("uid") or "").strip()
            image_url = (body.get("image_url") or "").strip()
            text = (body.get("text") or "").strip()
        except Exception:
            return respond(self, 400, {"ok": False, "error": "Invalid JSON"})
        if not uid or not image_url or not text:
            return respond(self, 400, {"ok": False, "error": "missing uid/image_url/text"})
        return self.do_GET()
