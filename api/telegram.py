# api/telegram.py — ultra-stable minimal bot (fast menus + async OpenAI)
import os, json, datetime, requests, threading, traceback
from textwrap import dedent
from http.server import BaseHTTPRequestHandler

# ===== ENV =====
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

# Optional free daily quota (Upstash)
REDIS_URL = os.getenv("UPSTASH_REDIS_REST_URL", "")
REDIS_TOKEN = os.getenv("UPSTASH_REDIS_REST_TOKEN", "")
FREE_DAILY = int(os.getenv("FREE_DAILY", "3"))

# ===== CORE UTILS =====
def log(*a): 
    try: print(*a, flush=True)
    except: pass

def rget(k):
    if not REDIS_URL or not REDIS_TOKEN: return None
    try:
        r = requests.get(f"{REDIS_URL}/get/{k}",
                         headers={"Authorization": f"Bearer {REDIS_TOKEN}"}, timeout=5)
        return r.json().get("result") if r.status_code == 200 else None
    except: return None

def rincr(k):
    if not REDIS_URL or not REDIS_TOKEN: return
    try: requests.get(f"{REDIS_URL}/incr/{k}",
                      headers={"Authorization": f"Bearer {REDIS_TOKEN}"}, timeout=5)
    except: pass

def today_key(uid): 
    return f"user:{uid}:uses:{datetime.date.today().isoformat()}"

def quota_ok(uid):
    if not REDIS_URL or not REDIS_TOKEN: return True
    v = rget(today_key(uid))
    try: return int(v or 0) < FREE_DAILY
    except: return True

def inc_quota(uid): 
    if REDIS_URL and REDIS_TOKEN: rincr(today_key(uid))

# ===== TELEGRAM =====
def tg(method, payload):
    if not BOT_TOKEN: return
    try:
        requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/{method}",
                      json=payload, timeout=10)
    except Exception as e: log("tg err", e)

def send(chat, text, kb=None):
    data = {"chat_id": chat, "text": text, "parse_mode": "Markdown"}
    if kb: data["reply_markup"] = kb
    tg("sendMessage", data)

MAIN_MENU = {
    "inline_keyboard": [
        [{"text": "⚡ Generate Openers", "callback_data": "gen_openers"}],
        [{"text": "📝 Generate Post", "callback_data": "gen_post"}],
    ]
}

# ===== OPENAI =====
def llm(prompt):
    if not OPENAI_API_KEY: return "⚠️ Missing OpenAI key"
    try:
        r = requests.post("https://api.openai.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {OPENAI_API_KEY}"},
            json={
                "model": OPENAI_MODEL,
                "messages":[
                    {"role":"system","content":"You are a LinkedIn content creator bot."},
                    {"role":"user","content":prompt}
                ],
                "temperature":0.7
            },
            timeout=20)
        if r.status_code == 200:
            return r.json()["choices"][0]["message"]["content"].strip()
        else:
            return "❌ OpenAI error: " + r.text
    except Exception as e:
        log("openai err", e)
        return "⚠️ AI temporarily unavailable."

# ===== BUSINESS =====
def generate_openers(chat, uid, topic):
    if not quota_ok(uid):
        send(chat, f"⚠️ You reached your {FREE_DAILY} free prompts for today.")
        return
    inc_quota(uid)
    send(chat, "⚙️ Generating openers... please wait ⏳")
    def job():
        txt = llm(f"Generate 8 LinkedIn-style openers about {topic}. Each 1 line.")
        send(chat, txt, kb=MAIN_MENU)
    threading.Thread(target=job, daemon=True).start()

def generate_post(chat, uid, topic):
    if not quota_ok(uid):
        send(chat, f"⚠️ You reached your {FREE_DAILY} free prompts for today.")
        return
    inc_quota(uid)
    send(chat, "⚙️ Writing a full post... please wait ⏳")
    def job():
        txt = llm(f"Write a concise LinkedIn post about {topic}, 8 lines + CTA.")
        send(chat, txt, kb=MAIN_MENU)
    threading.Thread(target=job, daemon=True).start()

# ===== ROUTING =====
def handle_message(msg):
    chat = msg["chat"]["id"]
    uid = msg["from"]["id"]
    text = (msg.get("text") or "").strip()

    if text.startswith("/start") or text.startswith("/menu"):
        send(chat, "🚀 *LinkedIn Content AI*\nChoose an action:", kb=MAIN_MENU)
        return

    # Detect quick commands
    if text.startswith("/openers"):
        topic = text.replace("/openers", "", 1).strip()
        return generate_openers(chat, uid, topic)
    if text.startswith("/post"):
        topic = text.replace("/post", "", 1).strip()
        return generate_post(chat, uid, topic)

    # If user replies after a button
    if text.lower().startswith("openers:"):
        topic = text.split(":",1)[-1].strip()
        return generate_openers(chat, uid, topic)
    if text.lower().startswith("post:"):
        topic = text.split(":",1)[-1].strip()
        return generate_post(chat, uid, topic)

    send(chat, "💡 Type /openers <topic> or /post <topic>", kb=MAIN_MENU)

def handle_callback(cb):
    cb_id  = cb["id"]
    chat   = cb["message"]["chat"]["id"]
    uid    = cb["from"]["id"]
    data   = cb["data"]

    if data == "gen_openers":
        tg("answerCallbackQuery", {"callback_query_id": cb_id, "text":"Type your topic."})
        send(chat, "✍️ Type your topic prefixed with:\n*Openers:* your topic")
        return
    if data == "gen_post":
        tg("answerCallbackQuery", {"callback_query_id": cb_id, "text":"Type your topic."})
        send(chat, "✍️ Type your topic prefixed with:\n*Post:* your topic")
        return

    tg("answerCallbackQuery", {"callback_query_id": cb_id, "text":"Invalid"})

def process(update):
    if "message" in update: handle_message(update["message"])
    elif "callback_query" in update: handle_callback(update["callback_query"])

# ===== HANDLER =====
class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        self.send_response(200)
        self.end_headers()
        try:
            n = int(self.headers.get("content-length") or 0)
            body = self.rfile.read(n)
            update = json.loads(body.decode("utf-8") or "{}")
        except Exception:
            return
        threading.Thread(target=lambda: process(update), daemon=True).start()

    def do_GET(self):
        self.send_response(200); self.end_headers()
        self.wfile.write(b"OK")
