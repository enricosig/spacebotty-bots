from http.server import BaseHTTPRequestHandler
import os, json, datetime, requests, threading, traceback
from textwrap import dedent

BOT_TOKEN      = os.getenv("TELEGRAM_BOT_TOKEN", "")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_MODEL   = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

REDIS_URL   = os.getenv("UPSTASH_REDIS_REST_URL", "")
REDIS_TOKEN = os.getenv("UPSTASH_REDIS_REST_TOKEN", "")
FREE_DAILY  = int(os.getenv("FREE_DAILY", "2"))

OPENAI_TIMEOUT = int(os.getenv("OPENAI_HTTP_TIMEOUT", "12"))
TG_TIMEOUT     = int(os.getenv("REQ_TIMEOUT", "10"))

def log(*a):
    try: print(*a, flush=True)
    except: pass

def _h(): return {"Authorization": f"Bearer {REDIS_TOKEN}"} if REDIS_TOKEN else {}
def rget(k):
    if not REDIS_URL or not REDIS_TOKEN: return None
    try:
        r = requests.get(f"{REDIS_URL}/get/{k}", headers=_h(), timeout=6)
        return r.json().get("result") if r.status_code == 200 else None
    except Exception as e:
        log("rget err", repr(e)); return None
def rsetex(k, s, v):
    if not REDIS_URL or not REDIS_TOKEN: return
    try: requests.get(f"{REDIS_URL}/setex/{k}/{s}/{v}", headers=_h(), timeout=6)
    except Exception as e: log("rsetex err", repr(e))
def rincr(k):
    if not REDIS_URL or not REDIS_TOKEN: return
    try: requests.get(f"{REDIS_URL}/incr/{k}", headers=_h(), timeout=6)
    except Exception as e: log("rincr err", repr(e))

def today_key(uid): return f"user:{uid}:uses:{datetime.date.today().isoformat()}"

def tg(method, payload):
    if not BOT_TOKEN:
        log("TELEGRAM_BOT_TOKEN missing"); return None
    try:
        return requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/{method}", json=payload, timeout=TG_TIMEOUT)
    except Exception as e:
        log("tg err", method, repr(e)); return None

def reply(chat_id, text, keyboard=None):
    data = {"chat_id": chat_id, "text": text, "parse_mode": "Markdown"}
    if keyboard: data["reply_markup"] = keyboard
    tg("sendMessage", data)

def answer_cb(cb_id, text=""):
    tg("answerCallbackQuery", {"callback_query_id": cb_id, "text": text})

SYSTEM_PROMPT = "You are an English content strategist for LinkedIn. Return only the requested content, clear and scannable."
def supports_temp(model): return "gpt-5-mini" not in (model or "")

def llm(prompt):
    if not OPENAI_API_KEY:
        return "⚠️ OPENAI_API_KEY not set."
    body = {
        "model": OPENAI_MODEL,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt}
        ]
    }
    if supports_temp(OPENAI_MODEL):
        body["temperature"] = 0.7
    try:
        r = requests.post("https://api.openai.com/v1/chat/completions",
                          headers={"Authorization": f"Bearer {OPENAI_API_KEY}"},
                          json=body, timeout=OPENAI_TIMEOUT)
        if r.status_code >= 400:
            try: msg = (r.json().get("error") or {}).get("message","")
            except: msg = r.text
            log("OpenAI error:", msg)
            return "Quick draft (fallback):\n• Hook\n• 3 bullets with specifics\n• CTA"
        return r.json()["choices"][0]["message"]["content"].strip()
    except Exception as e:
        log("OpenAI exception:", repr(e))
        return "Quick draft (offline):\n• Hook\n• 3 bullets\n• CTA"

MAIN_MENU = {
    "inline_keyboard": [
        [{"text": "⚡ Openers", "callback_data": "m:openers"}],
        [{"text": "📝 Full Post", "callback_data": "m:post"}],
        [{"text": "✨ Presets", "callback_data": "m:presets"}],
        [{"text": "ℹ️ Status", "callback_data": "m:status"}],
    ]
}

def send_welcome(chat_id):
    reply(chat_id, dedent(f"""
    🚀 *LinkedIn Content AI*
    Generate hooks and full posts.

    *Commands*
    • /openers <topic>
    • /post <topic>

    *Free quota:* {FREE_DAILY} prompts/day
    """), keyboard=MAIN_MENU)

def send_presets(chat_id):
    reply(chat_id, dedent("""
    *Presets*
    /openers grow your LinkedIn audience
    /post 3-step framework to scale on LinkedIn
    """))

def send_status(chat_id, uid):
    used = rget(today_key(uid)) if REDIS_URL and REDIS_TOKEN else None
    reply(chat_id, f"Daily usage: {used or 0}/{FREE_DAILY}")

def quota_ok(uid):
    if not REDIS_URL or not REDIS_TOKEN: return True
    used = rget(today_key(uid))
    try: used = int(used or 0)
    except: used = 0
    return used < FREE_DAILY

def inc_quota(uid):
    if not REDIS_URL or not REDIS_TOKEN: return
    k = today_key(uid)
    if rget(k) is None:
        now = datetime.datetime.now()
        midnight = datetime.datetime.combine((now+datetime.timedelta(days=1)).date(), datetime.time.min)
        ttl = int((midnight - now).total_seconds())
        rsetex(k, ttl, "0")
    rincr(k)

def do_openers(chat_id, uid, topic):
    if not topic:
        reply(chat_id, "Give me a topic: `/openers grow your LinkedIn audience`"); return
    if not quota_ok(uid):
        reply(chat_id, f"⚠️ You've used your {FREE_DAILY} free prompts today. Try again tomorrow."); return
    prompt = dedent(f"""Generate 10 high-impact LinkedIn openers (one line each).
Mix formats: provocative question, counterintuitive fact, promise, common mistake, opinion.
Topic: {topic}""")
    text = llm(prompt)
    reply(chat_id, text)
    inc_quota(uid)

def do_post(chat_id, uid, topic):
    if not topic:
        reply(chat_id, "Give me a topic: `/post 3-step framework to grow on LinkedIn`"); return
    if not quota_ok(uid):
        reply(chat_id, f"⚠️ You've used your {FREE_DAILY} free prompts today. Try again tomorrow."); return
    prompt = dedent(f"""Write a LinkedIn post with:
- Hook (1 line)
- 6–9 short lines with specifics
- CTA (1 line)
Topic: {topic}""")
    text = llm(prompt)
    reply(chat_id, text)
    inc_quota(uid)

def handle_message(msg):
    chat_id = msg["chat"]["id"]
    uid     = msg["from"]["id"]
    text    = msg.get("text","") or ""

    if text.startswith("/start"):
        send_welcome(chat_id); return
    if text.startswith("/openers"):
        do_openers(chat_id, uid, text.replace("/openers","",1).strip()); return
    if text.startswith("/post"):
        do_post(chat_id, uid, text.replace("/post","",1).strip()); return
    send_welcome(chat_id)

def handle_callback(cb):
    cb_id  = cb["id"]
    chat_id= cb["message"]["chat"]["id"]
    uid    = cb["from"]["id"]
    data   = cb.get("data","")
    try:
        if data == "m:openers":
            answer_cb(cb_id); reply(chat_id, "Send: `/openers your topic`")
        elif data == "m:post":
            answer_cb(cb_id); reply(chat_id, "Send: `/post your topic`")
        elif data == "m:presets":
            answer_cb(cb_id); send_presets(chat_id)
        elif data == "m:status":
            answer_cb(cb_id); send_status(chat_id, uid)
        else:
            answer_cb(cb_id, "Unknown action")
    except Exception:
        answer_cb(cb_id); log("callback err", traceback.format_exc())

def process_update(update):
    if "message" in update:
        handle_message(update["message"])
    elif "edited_message" in update:
        handle_message(update["edited_message"])
    elif "callback_query" in update:
        handle_callback(update["callback_query"])

class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        self.send_response(200); self.send_header("Content-Type","text/plain"); self.end_headers()
        try:
            n = int(self.headers.get("content-length") or 0)
            raw = self.rfile.read(n) if n else b"{}"
            update = json.loads(raw.decode("utf-8") or "{}")
        except Exception:
            log("parse err"); return
        def _run():
            try: process_update(update)
            except Exception: log("update err", traceback.format_exc())
        threading.Thread(target=_run, daemon=True).start()

    def do_GET(self):
        self.send_response(200); self.end_headers()
        try: self.wfile.write(b"OK")
        except: pass
