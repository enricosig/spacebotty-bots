# api/telegram.py
import os, json, datetime, requests, threading, traceback
from textwrap import dedent
from urllib.parse import quote_plus
from http.server import BaseHTTPRequestHandler

# ===== Env =====
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "https://spacebotty-bots.vercel.app")
REDIS_URL = os.getenv("UPSTASH_REDIS_REST_URL", "")
REDIS_TOKEN = os.getenv("UPSTASH_REDIS_REST_TOKEN", "")

FREE_DAILY = int(os.getenv("FREE_DAILY", "2"))

OPENAI_HTTP_TIMEOUT = int(os.getenv("OPENAI_HTTP_TIMEOUT", "8"))  # corto per evitare timeout Vercel/Telegram
REQ_TIMEOUT = int(os.getenv("REQ_TIMEOUT", "10"))

def log(*args):
    try: print(*args, flush=True)
    except: pass

# ===== Redis (Upstash) =====
def _h(): return {"Authorization": f"Bearer {REDIS_TOKEN}"} if REDIS_TOKEN else {}
def rget(k):
    if not REDIS_URL or not REDIS_TOKEN: return None
    try:
        r = requests.get(f"{REDIS_URL}/get/{k}", headers=_h(), timeout=5)
        return r.json().get("result") if r.status_code == 200 else None
    except Exception as e:
        log("rget err", repr(e)); return None
def rsetex(k, s, v):
    if not REDIS_URL or not REDIS_TOKEN: return
    try: requests.get(f"{REDIS_URL}/setex/{k}/{s}/{v}", headers=_h(), timeout=5)
    except Exception as e: log("rsetex err", repr(e))
def rset(k, v):
    if not REDIS_URL or not REDIS_TOKEN: return
    try: requests.get(f"{REDIS_URL}/set/{k}/{v}", headers=_h(), timeout=5)
    except Exception as e: log("rset err", repr(e))
def rincr(k):
    if not REDIS_URL or not REDIS_TOKEN: return
    try: requests.get(f"{REDIS_URL}/incr/{k}", headers=_h(), timeout=5)
    except Exception as e: log("rincr err", repr(e))

def today_key(uid): return f"user:{uid}:uses:{datetime.date.today().isoformat()}"

# ===== Telegram helpers =====
def tg(method, payload):
    if not BOT_TOKEN:
        log("TELEGRAM_BOT_TOKEN missing")
        return None
    try:
        return requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/{method}", json=payload, timeout=REQ_TIMEOUT)
    except Exception as e:
        log("tg err", method, repr(e))
        return None

def reply(chat_id, text, keyboard=None):
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "Markdown"}
    if keyboard: payload["reply_markup"] = keyboard
    tg("sendMessage", payload)

# ===== LLM =====
SYSTEM_PROMPT = "You are an English content strategist for LinkedIn. Return only the requested content, clear and scannable."

def _supports_temp(model):
    # alcuni modelli (es. gpt-5-mini) non supportano temperature != default
    return "gpt-5-mini" not in (model or "")

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
    if _supports_temp(OPENAI_MODEL):
        body["temperature"] = 0.7

    try:
        r = requests.post(
            "https://api.openai.com/v1/chat/completions",
            json=body,
            headers={"Authorization": f"Bearer {OPENAI_API_KEY}"},
            timeout=OPENAI_HTTP_TIMEOUT
        )
        if r.status_code >= 400:
            # graceful downgrade
            try:
                err = r.json()
                msg = (err.get("error") or {}).get("message","")
                log("OpenAI error:", msg)
            except: pass
            return "Here’s a concise LinkedIn draft:\n\n• Hook: A bold claim that challenges a common belief.\n• Insight 1: A specific lesson with an example.\n• Insight 2: A counterintuitive tactic.\n• CTA: Ask a sharp question to spark comments."
        return r.json()["choices"][0]["message"]["content"].strip()
    except Exception as e:
        log("OpenAI exception", repr(e))
        return "Quick draft (offline mode):\n\nHook — What nobody tells you about this.\n1) Practical step\n2) Small win\n3) Mistake to avoid\nCTA — What’s your experience?"

# ===== Business logic (ridotta ma robusta) =====
def quota_ok(uid):
    if not REDIS_URL or not REDIS_TOKEN:
        return True  # se non c'è Redis, non bloccare
    k = today_key(uid)
    used = rget(k)
    try: used = int(used or 0)
    except: used = 0
    return used < FREE_DAILY

def inc_quota(uid):
    if not REDIS_URL or not REDIS_TOKEN: return
    k = today_key(uid)
    if rget(k) is None:
        # set fino a fine giornata
        now = datetime.datetime.now()
        ttl = int((datetime.datetime.combine((now+datetime.timedelta(days=1)).date(), datetime.time.min) - now).total_seconds())
        rsetex(k, ttl, "0")
    rincr(k)

def connect_button(uid):
    url = f"{PUBLIC_BASE_URL}/api/oauth/start?uid={uid}"
    return {"inline_keyboard":[[{"text":"🔗 Connect LinkedIn","url": url}]]}

def btn_post_text(uid, text):
    url = f"{PUBLIC_BASE_URL}/api/post?uid={uid}&text={quote_plus(text)}"
    return {"inline_keyboard":[[{"text":"📤 Post on LinkedIn","url": url}]]}

def do_openers(chat_id, uid, topic):
    if not quota_ok(uid):
        reply(chat_id, f"⚠️ You've used your {FREE_DAILY} free prompts today. Try again tomorrow or upgrade.")
        return
    if not topic:
        reply(chat_id, "Give me a topic: /openers grow your LinkedIn audience"); return
    prompt = dedent(f"""Generate 10 high-impact LinkedIn openers (one line each).
Mix: provocative question, counterintuitive fact, promise, common mistake, opinion.
Topic: {topic}""")
    text = llm(prompt)
    reply(chat_id, text)
    inc_quota(uid)

def do_post(chat_id, uid, topic):
    if not quota_ok(uid):
        reply(chat_id, f"⚠️ You've used your {FREE_DAILY} free prompts today. Try again tomorrow or upgrade.")
        return
    if not topic:
        reply(chat_id, "Give me a topic: /post 3-step framework to grow on LinkedIn"); return
    prompt = dedent(f"""Write a LinkedIn post with:
- Hook (1 line)
- 6–9 short lines with specifics
- CTA (1 line)
Topic: {topic}""")
    text = llm(prompt)
    kb = btn_post_text(uid, text)
    reply(chat_id, text, keyboard=kb)
    inc_quota(uid)

def process_update(update):
    try:
        msg = update.get("message") or update.get("edited_message")
        if not msg: return

        chat_id = msg["chat"]["id"]
        uid = msg["from"]["id"]
        text = msg.get("text","")

        if text.startswith("/start"):
            reply(chat_id, dedent(f"""
            🚀 *LinkedIn Growth AI*
            /openers <topic> → 10 hooks
            /post <topic>    → full post
            /connect         → link LinkedIn
            """))
            return
        if text.startswith("/connect"):
            reply(chat_id, "Link your LinkedIn:", keyboard=connect_button(uid)); return
        if text.startswith("/openers"):
            do_openers(chat_id, uid, text.replace("/openers","",1).strip()); return
        if text.startswith("/post"):
            do_post(chat_id, uid, text.replace("/post","",1).strip()); return

        reply(chat_id, "Commands: /start /openers /post /connect")
    except Exception as e:
        log("process_update err", traceback.format_exc())

# ===== HTTP handler =====
class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        # 1) Early ACK: rispondiamo SUBITO 200 per evitare 500/timeout su Telegram
        self.send_response(200)
        self.send_header("Content-Type","text/plain")
        self.end_headers()
        try:
            raw = self.rfile.read(int(self.headers.get("content-length","0") or 0))
            update = json.loads(raw.decode("utf-8")) if raw else {}
        except Exception:
            log("parse body err")
            return

        # 2) Processiamo in un thread rapido (così la risposta 200 è già partita)
        def _run():
            try:
                process_update(update)
            except Exception:
                log("update thread err", traceback.format_exc())
        threading.Thread(target=_run, daemon=True).start()

    def do_GET(self):
        self.send_response(200); self.end_headers()
        try: self.wfile.write(b"OK"); 
        except: pass
