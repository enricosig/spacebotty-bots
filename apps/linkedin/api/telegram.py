# apps/linkedin/api/telegram.py
import os, json, datetime, requests, traceback
from textwrap import dedent
from http.server import BaseHTTPRequestHandler

def log(*args):
    try: print(*args, flush=True)
    except: pass

# === ENV ===
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
# Preferred model can still be overridden via env; default to 5-mini
PREFERRED_MODEL = os.getenv("OPENAI_MODEL", "gpt-5-mini")

REDIS_URL = os.getenv("UPSTASH_REDIS_REST_URL")
REDIS_TOKEN = os.getenv("UPSTASH_REDIS_REST_TOKEN")

ENABLE_TG_PAY = os.getenv("ENABLE_TELEGRAM_PAYMENTS", "false").lower() == "true"
PROVIDER_TOKEN = os.getenv("PROVIDER_TOKEN", "")
PREMIUM_PRICE_EUR = int(os.getenv("PREMIUM_PRICE_EUR", "7"))
PREMIUM_TITLE = os.getenv("PREMIUM_TITLE", "Premium 30 days")
PREMIUM_DESCRIPTION = os.getenv("PREMIUM_DESCRIPTION", "30-day pass: unlimited prompts & priority")
PREMIUM_DAYS = int(os.getenv("PREMIUM_DAYS", "30"))

FREE_DAILY = int(os.getenv("FREE_DAILY", "3"))
PREMIUM_CODE = os.getenv("PREMIUM_CODE", "VIP-2025")
STRIPE_PAYMENT_LINK = os.getenv("STRIPE_PAYMENT_LINK", "")

log("BOOT env:",
    "TOKEN_SET" if BOT_TOKEN else "TOKEN_MISSING",
    "OPENAI_SET" if OPENAI_API_KEY else "OPENAI_MISSING",
    f"PREFERRED_MODEL={PREFERRED_MODEL}",
    "REDIS_URL_SET" if REDIS_URL else "REDIS_URL_MISSING",
    "REDIS_TOKEN_SET" if REDIS_TOKEN else "REDIS_TOKEN_MISSING",
)

# === Upstash helpers ===
def _h(): return {"Authorization": f"Bearer {REDIS_TOKEN}"} if REDIS_TOKEN else {}
def rget(key):
    if not REDIS_URL or not REDIS_TOKEN: return None
    try:
        r = requests.get(f"{REDIS_URL}/get/{key}", headers=_h(), timeout=8)
        return r.json().get("result") if r.status_code == 200 else None
    except Exception as e: log("rget", repr(e)); return None
def rsetex(key, seconds, value):
    if not REDIS_URL or not REDIS_TOKEN: return
    try: requests.get(f"{REDIS_URL}/setex/{key}/{seconds}/{value}", headers=_h(), timeout=8)
    except Exception as e: log("rsetex", repr(e))
def rincr(key):
    if not REDIS_URL or not REDIS_TOKEN: return
    try: requests.get(f"{REDIS_URL}/incr/{key}", headers=_h(), timeout=8)
    except Exception as e: log("rincr", repr(e))
def today_key(uid): return f"user:{uid}:uses:{datetime.date.today().isoformat()}"
def premium_key(uid): return f"user:{uid}:premium"
def has_premium(uid): return rget(premium_key(uid)) == "1"
def quota_ok(uid):
    if has_premium(uid): return True
    k = today_key(uid); uses = rget(k)
    if uses is None:
        now = datetime.datetime.now()
        ttl = int((datetime.datetime.combine((now+datetime.timedelta(days=1)).date(), datetime.time.min) - now).total_seconds())
        rsetex(k, ttl, "0"); uses = "0"
    try: return int(uses) < FREE_DAILY
    except: return True
def inc_quota(uid): rincr(today_key(uid))

# === Telegram helpers ===
def tg(method, payload):
    if not BOT_TOKEN: log("TOKEN missing"); return None
    try: return requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/{method}", json=payload, timeout=12)
    except Exception as e: log("tg", repr(e)); return None
def reply(chat_id, text, parse_mode="Markdown"):
    try: tg("sendMessage", {"chat_id": chat_id, "text": text, "parse_mode": parse_mode})
    except Exception as e: log("sendMessage", repr(e))
def set_premium(uid, days=PREMIUM_DAYS): rsetex(premium_key(uid), int(days)*86400, "1")

# === OpenAI ===
SYSTEM_PROMPT = "You are an English content strategist for LinkedIn. Return only the requested content, clear and scannable."

def _openai_chat(model, prompt):
    body = {
        "model": model, "temperature": 0.7,
        "messages": [{"role":"system","content":SYSTEM_PROMPT},
                     {"role":"user","content":prompt}]
    }
    r = requests.post("https://api.openai.com/v1/chat/completions",
                      json=body, headers={"Authorization": f"Bearer {OPENAI_API_KEY}"}, timeout=25)
    return r

def llm(prompt):
    if not OPENAI_API_KEY:
        return "⚠️ OPENAI_API_KEY not set; ask the admin to configure it."
    primary = PREFERRED_MODEL
    fallback = "gpt-4o-mini"
    tried = []

    # try primary
    try:
        tried.append(primary)
        r = _openai_chat(primary, prompt)
        if r.status_code == 200:
            return r.json()["choices"][0]["message"]["content"].strip()

        # inspect error to decide fallback
        err = None
        try: err = r.json()
        except: err = {"error": r.text}

        code = (err.get("error") or {}).get("code")
        msg = (err.get("error") or {}).get("message","")
        log("OpenAI primary error:", primary, r.status_code, err)

        if r.status_code in (404,) or code in ("model_not_found",) or "model not found" in msg.lower():
            # try fallback
            tried.append(fallback)
            r2 = _openai_chat(fallback, prompt)
            if r2.status_code == 200:
                return r2.json()["choices"][0]["message"]["content"].strip()
            log("OpenAI fallback error:", fallback, r2.status_code, r2.text)
            return "⚠️ OpenAI model not found for this account. Please set OPENAI_MODEL to an available model (e.g., gpt-4o-mini) and redeploy."
        if r.status_code in (429, 402) or code in ("insufficient_quota",) or "quota" in msg.lower():
            # try fallback in case only 5-mini is blocked
            tried.append(fallback)
            r2 = _openai_chat(fallback, prompt)
            if r2.status_code == 200:
                return r2.json()["choices"][0]["message"]["content"].strip()
            return "⚠️ Your OpenAI quota is exhausted for this key. Add billing/credits and retry."
        return "⚠️ OpenAI request failed. Please try again later."
    except Exception:
        log("OpenAI exception:", traceback.format_exc())
        return "⚠️ OpenAI request failed. Please try again in a minute."

# === Commands ===
def cmd_presets(chat_id):
    reply(chat_id, "Presets (LinkedIn):\n"
                   "/openers grow your LinkedIn audience as a PM\n"
                   "/post case study: reduce churn in B2B SaaS\n"
                   "/comment personal branding for engineers\n"
                   "/contentplan AI consultant in B2B")

def cmd_start(chat_id):
    reply(chat_id, dedent(f"""
    🚀 **Welcome to *LinkedIn Growth AI***
    Your assistant for creating LinkedIn posts, hooks, and strategies that turn views into clients.

    ✍️ *What you can do right now:*
    • /openers → viral openers for your posts
    • /post → full post (headline, body, CTA)
    • /comment → sharp comments to increase reach
    • /contentplan → 7-day content calendar

    💎 You have {FREE_DAILY} free prompts per day.
    Unlock unlimited usage → **/buy** (€7 / 30 days) or **/premium** (€9 / month).

    👉 Try /presets to get instant inspiration.
    """))

def ensure_quota_or_block(chat_id, uid):
    if quota_ok(uid): return True
    reply(chat_id, dedent(f"""
    ⚠️ You’ve used your {FREE_DAILY} free prompts for today.

    🚀 Go *Premium* to unlock:
    ✅ Unlimited prompts
    ⚡ Faster responses
    💡 Advanced personal-branding templates

    👉 **/buy** (€7 / 30 days)  |  **/premium** (€9 / month)
    """)); return False

def cmd_premium(chat_id):
    msg = ("💎 *Spacebotty Premium* — grow faster, publish more\n"
           "Unlimited prompts · Priority responses · Advanced templates\n\n"
           "⚡ *Two ways to upgrade:*\n"
           "1) **/buy** — In-app 30-day pass (€7)\n")
    if STRIPE_PAYMENT_LINK:
        tg("sendMessage", {"chat_id": chat_id, "text": msg + "2) **Stripe** — Monthly subscription (€9)\n",
                           "parse_mode": "Markdown",
                           "reply_markup": {"inline_keyboard": [[{"text":"Open Stripe (€9 / month)","url":STRIPE_PAYMENT_LINK}]]}})
    else:
        reply(chat_id, msg)

def cmd_redeem(chat_id, uid, args):
    code = (args[0] if args else "").strip()
    if not code: reply(chat_id, "Usage: /redeem <CODE>"); return
    if code == PREMIUM_CODE: set_premium(uid, PREMIUM_DAYS); reply(chat_id, "✅ Premium activated.")
    else: reply(chat_id, "❌ Invalid code.")

def cmd_buy(chat_id):
    if not ENABLE_TG_PAY or not PROVIDER_TOKEN:
        reply(chat_id, "In-app payments not configured. Use /premium for alternatives."); return
    tg("sendInvoice", {"chat_id": chat_id,"title": PREMIUM_TITLE,"description": PREMIUM_DESCRIPTION,
                       "payload": "premium-purchase-30d","provider_token": PROVIDER_TOKEN,
                       "currency": "EUR","prices":[{"label":PREMIUM_TITLE,"amount":PREMIUM_PRICE_EUR*100}]})

def handle_pre_checkout(pre_checkout_query): tg("answerPreCheckoutQuery", {"pre_checkout_query_id": pre_checkout_query["id"], "ok": True})
def handle_successful_payment(chat_id, uid): set_premium(uid, PREMIUM_DAYS); reply(chat_id, "🎉 Payment received! Premium activated for 30 days.")
def cmd_status(chat_id, uid): reply(chat_id, f"*Status*\nPremium: {'✅ active' if has_premium(uid) else '❌ not active'}\nToday: {(rget(today_key(uid)) or '0')}/{FREE_DAILY}", "Markdown")

# Generators
def do_openers(chat_id, uid, topic):
    if not ensure_quota_or_block(chat_id, uid): return
    if not topic: reply(chat_id, "Give me a topic: /openers grow your LinkedIn audience"); return
    prompt = dedent(f"""Generate *10 high-impact openers* (1 line each) for LinkedIn posts.
Mix formats: provocative question, counterintuitive fact, promise, common mistake, opinion.
Topic: {topic}""")
    reply(chat_id, llm(prompt)); inc_quota(uid)

def do_post(chat_id, uid, topic):
    if not ensure_quota_or_block(chat_id, uid): return
    if not topic: reply(chat_id, "Give me a topic: /post 3-step framework to grow on LinkedIn"); return
    prompt = dedent(f"""Write a *LinkedIn post* with:
- Headline (1 line) with strong hook
- Body: 6–10 short lines, spaced for readability (bullets if useful)
- Final CTA (1 line)
Be specific and practical; avoid empty buzzwords.
Topic: {topic}""")
    reply(chat_id, llm(prompt)); inc_quota(uid)

def do_comment(chat_id, uid, topic):
    if not ensure_quota_or_block(chat_id, uid): return
    if not topic: reply(chat_id, "Give me a topic: /comment personal branding for PMs"); return
    prompt = dedent(f"""Generate *5 sharp comments* for LinkedIn posts on the given topic.
Each: 1–2 sentences, concrete value or original angle; no empty praise.
Topic: {topic}""")
    reply(chat_id, llm(prompt)); inc_quota(uid)

def do_contentplan(chat_id, uid, niche):
    if not ensure_quota_or_block(chat_id, uid): return
    if not niche: reply(chat_id, "Give me a niche: /contentplan B2B SaaS"); return
    prompt = dedent(f"""Create a *7-day content plan* for LinkedIn.
For each day: Post title + Unique angle + Promised outcome (1–2 lines).
Niche: {niche}""")
    reply(chat_id, llm(prompt)); inc_quota(uid)

# HTTP handler
class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        try:
            body = self.rfile.read(int(self.headers.get("content-length","0")))
            update = json.loads(body.decode("utf-8"))
            if "pre_checkout_query" in update:
                handle_pre_checkout(update["pre_checkout_query"]); return self._ok()
            msg = update.get("message") or update.get("edited_message")
            if not msg: log("No message in update:", update); return self._ok()

            chat_id = msg["chat"]["id"]; uid = msg["from"]["id"]; text = msg.get("text","")
            if "successful_payment" in msg:
                handle_successful_payment(chat_id, uid); return self._ok()

            if   text.startswith("/start"):        cmd_start(chat_id)
            elif text.startswith("/premium"):      cmd_premium(chat_id)
            elif text.startswith("/buy"):          cmd_buy(chat_id)
            elif text.startswith("/status"):       cmd_status(chat_id, uid)
            elif text.startswith("/presets"):      cmd_presets(chat_id)
            elif text.startswith("/redeem"):
                parts = text.split(maxsplit=1); args = parts[1].split() if len(parts)>1 else []
                cmd_redeem(chat_id, uid, args)
            elif text.startswith("/openers"):      do_openers(chat_id, uid, text.replace("/openers","",1).strip())
            elif text.startswith("/post"):         do_post(chat_id, uid, text.replace("/post","",1).strip())
            elif text.startswith("/comment"):      do_comment(chat_id, uid, text.replace("/comment","",1).strip())
            elif text.startswith("/contentplan"):  do_contentplan(chat_id, uid, text.replace("/contentplan","",1).strip())
            else:
                reply(chat_id, "Commands: /openers /post /comment /contentplan /presets /status /premium /redeem /buy")
            self._ok()
        except Exception:
            log("FATAL do_POST:", traceback.format_exc()); self._ok()

    def do_GET(self):
        self._ok()
        try: self.wfile.write(b"OK")
        except: pass

    def _ok(self):
        self.send_response(200); self.send_header("Content-Type","text/plain"); self.end_headers()
