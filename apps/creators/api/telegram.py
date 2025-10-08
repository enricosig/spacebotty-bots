# apps/creators/api/telegram.py
import os, json, datetime, requests, sys, traceback
from textwrap import dedent
from http.server import BaseHTTPRequestHandler

def log(*args):
    try: print(*args, flush=True)
    except: pass

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-5-mini")
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
    "REDIS_URL_SET" if REDIS_URL else "REDIS_URL_MISSING",
    "REDIS_TOKEN_SET" if REDIS_TOKEN else "REDIS_TOKEN_MISSING")

def rget(k):
    if not REDIS_URL or not REDIS_TOKEN: return None
    try: return requests.get(f"{REDIS_URL}/get/{k}", headers={"Authorization": f"Bearer {REDIS_TOKEN}"}, timeout=8).json().get("result")
    except Exception as e: log("rget", repr(e)); return None
def rsetex(k, s, v):
    if not REDIS_URL or not REDIS_TOKEN: return
    try: requests.get(f"{REDIS_URL}/setex/{k}/{s}/{v}", headers={"Authorization": f"Bearer {REDIS_TOKEN}"}, timeout=8)
    except Exception as e: log("rsetex", repr(e))
def rincr(k):
    if not REDIS_URL or not REDIS_TOKEN: return
    try: requests.get(f"{REDIS_URL}/incr/{k}", headers={"Authorization": f"Bearer {REDIS_TOKEN}"}, timeout=8)
    except Exception as e: log("rincr", repr(e))

def today_key(uid): return f"user:{uid}:uses:{datetime.date.today().isoformat()}"
def premium_key(uid): return f"user:{uid}:premium"
def has_premium(uid): return rget(premium_key(uid)) == "1"
def quota_ok(uid):
    if has_premium(uid): return True
    k = today_key(uid); uses = rget(k)
    if uses is None:
        now = datetime.datetime.now(); tomorrow = now + datetime.timedelta(days=1)
        ttl = int((datetime.datetime.combine(tomorrow.date(), datetime.time.min) - now).total_seconds())
        rsetex(k, ttl, "0"); uses = "0"
    try: return int(uses) < FREE_DAILY
    except: return True
def inc_quota(uid): rincr(today_key(uid))

def tg(method, payload):
    if not BOT_TOKEN: log("TOKEN missing"); return None
    try: return requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/{method}", json=payload, timeout=9)
    except Exception as e: log("tg", repr(e)); return None
def reply(chat_id, text, parse_mode="Markdown"):
    try: tg("sendMessage", {"chat_id": chat_id, "text": text, "parse_mode": parse_mode})
    except Exception as e: log("sendMessage", repr(e))

SYSTEM_PROMPT = "You are an English content strategist for TikTok/Instagram. Return only the requested content; short, punchy, ready to use."
def llm(prompt):
    if not OPENAI_API_KEY: return "⚠️ OPENAI_API_KEY not set."
    try:
        r = requests.post("https://api.openai.com/v1/chat/completions",
                          headers={"Authorization": f"Bearer {OPENAI_API_KEY}"},
                          json={"model": OPENAI_MODEL,"temperature":0.7,
                                "messages":[{"role":"system","content":SYSTEM_PROMPT},
                                            {"role":"user","content":prompt}]},
                          timeout=15)
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"].strip()
    except Exception as e:
        log("OpenAI", repr(e)); return "⚠️ OpenAI request failed. Try later."

def cmd_presets(chat_id):
    reply(chat_id, "Presets (Creators):\n"
                   "/hooks home workout tips\n"
                   "/reels quick editing tricks\n"
                   "/captions growth on TikTok\n"
                   "/ideas budget travel niche")

def cmd_start(chat_id):
    reply(chat_id, dedent(f"""
    🎬 **Welcome to *Creators AI***
    Your AI assistant for hooks, reels scripts, captions, and viral ideas.

    ⚡ Quick commands:
    • /hooks → 10 viral hooks
    • /reels → 5 short-form video scripts
    • /captions → captions with emojis + hashtags
    • /ideas → 10 fresh content ideas

    🧩 {FREE_DAILY} free prompts per day.
    💎 Need more? **/buy** (€7 / 30 days) or **/premium** (€9 / month).

    ✨ Try /presets to start in 10 seconds.
    """))

def ensure_quota_or_block(chat_id, uid):
    if quota_ok(uid): return True
    reply(chat_id, dedent(f"""
    💡 You’ve reached your {FREE_DAILY} free prompts for today.

    🔓 Unlock *unlimited prompts* with **/buy** (€7 / 30 days)
    or **/premium** (€9 / month).

    ✨ More ideas. More content. More reach.
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
    if code == PREMIUM_CODE: rsetex(premium_key(uid), PREMIUM_DAYS*86400, "1"); reply(chat_id, "✅ Premium activated.")
    else: reply(chat_id, "❌ Invalid code.")

def cmd_buy(chat_id):
    if not ENABLE_TG_PAY or not PROVIDER_TOKEN:
        reply(chat_id, "In-app payments not configured. Use /premium for alternatives."); return
    tg("sendInvoice", {"chat_id":chat_id,"title":PREMIUM_TITLE,"description":PREMIUM_DESCRIPTION,
                       "payload":"premium-purchase-30d","provider_token":PROVIDER_TOKEN,
                       "currency":"EUR","prices":[{"label":PREMIUM_TITLE,"amount":PREMIUM_PRICE_EUR*100}]})

def handle_pre_checkout(pre_checkout_query): tg("answerPreCheckoutQuery", {"pre_checkout_query_id": pre_checkout_query["id"], "ok": True})
def handle_successful_payment(chat_id, uid): rsetex(premium_key(uid), PREMIUM_DAYS*86400, "1"); reply(chat_id, "🎉 Premium activated for 30 days.")
def cmd_status(chat_id, uid): reply(chat_id, f"*Status*\nPremium: {'✅ active' if rget(premium_key(uid))=='1' else '❌ not active'}\nToday: {(rget(today_key(uid)) or '0')}/{FREE_DAILY}", "Markdown")

def do_hooks(chat_id, uid, topic):
    if not ensure_quota_or_block(chat_id, uid): return
    if not topic: reply(chat_id, "Give me a topic: /hooks Instagram growth"); return
    prompt = dedent(f"""Generate *10 viral hooks* (1 line each) for Reels/Shorts/TikTok.
Techniques: curiosity, shock, bold promise, common mistake, counterintuitive fact.
Topic: {topic}""")
    reply(chat_id, llm(prompt)); inc_quota(uid)

def do_reels(chat_id, uid, topic):
    if not ensure_quota_or_block(chat_id, uid): return
    if not topic: reply(chat_id, "Give me a topic: /reels office automation"); return
    prompt = dedent(f"""Create *5 short scripts* (~20–35s) with structure:
1) Hook (1 line)
2) Beat-by-beat (3–5 points)
3) CTA (1 line)
Topic: {topic}""")
    reply(chat_id, llm(prompt)); inc_quota(uid)

def do_captions(chat_id, uid, topic):
    if not ensure_quota_or_block(chat_id, uid): return
    if not topic: reply(chat_id, "Give me a topic: /captions TikTok growth"); return
    prompt = dedent(f"""Create *5 captions* for IG/TikTok.
- Human, direct tone
- 1–2 emojis per sentence
- End with 5–8 targeted hashtags
Topic: {topic}""")
    reply(chat_id, llm(prompt)); inc_quota(uid)

def do_ideas(chat_id, uid, topic):
    if not ensure_quota_or_block(chat_id, uid): return
    if not topic: reply(chat_id, "Give me a topic: /ideas home fitness"); return
    prompt = dedent(f"""Propose *10 content ideas* for the specified niche.
Each in 1–2 lines: idea + unique angle + promised outcome.
Topic: {topic}""")
    reply(chat_id, llm(prompt)); inc_quota(uid)

class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        try:
            body = self.rfile.read(int(self.headers.get("content-length","0"))); update = json.loads(body.decode("utf-8"))
            if "pre_checkout_query" in update: handle_pre_checkout(update["pre_checkout_query"]); return self._ok()
            msg = update.get("message") or update.get("edited_message")
            if not msg: log("No message in update:", update); return self._ok()
            chat_id = msg["chat"]["id"]; uid = msg["from"]["id"]; text = msg.get("text","")
            if "successful_payment" in msg: handle_successful_payment(chat_id, uid); return self._ok()

            if   text.startswith("/start"): cmd_start(chat_id)
            elif text.startswith("/premium"): cmd_premium(chat_id)
            elif text.startswith("/buy"): cmd_buy(chat_id)
            elif text.startswith("/status"): cmd_status(chat_id, uid)
            elif text.startswith("/presets"): cmd_presets(chat_id)
            elif text.startswith("/redeem"):
                parts = text.split(maxsplit=1); args = parts[1].split() if len(parts)>1 else []; cmd_redeem(chat_id, uid, args)
            elif text.startswith("/hooks"): do_hooks(chat_id, uid, text.replace("/hooks","",1).strip())
            elif text.startswith("/reels"): do_reels(chat_id, uid, text.replace("/reels","",1).strip())
            elif text.startswith("/captions"): do_captions(chat_id, uid, text.replace("/captions","",1).strip())
            elif text.startswith("/ideas"): do_ideas(chat_id, uid, text.replace("/ideas","",1).strip())
            else: reply(chat_id, "Commands: /hooks /reels /captions /ideas /presets /status /premium /redeem /buy")
            self._ok()
        except Exception:
            log("FATAL do_POST:", traceback.format_exc()); self._ok()
    def do_GET(self): self._ok(); 
    def _ok(self): self.send_response(200); self.send_header("Content-Type","text/plain"); self.end_headers(); 
    # no body to avoid issues
