import os, json, datetime, requests
from textwrap import dedent
from http.server import BaseHTTPRequestHandler

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-5-mini")
FREE_DAILY = int(os.getenv("FREE_DAILY", "3"))
PREMIUM_CODE = os.getenv("PREMIUM_CODE", "VIP-2025")
STRIPE_PAYMENT_LINK = os.getenv("STRIPE_PAYMENT_LINK", "")

REDIS_URL = os.getenv("UPSTASH_REDIS_REST_URL")
REDIS_TOKEN = os.getenv("UPSTASH_REDIS_REST_TOKEN")

def rget(key):
    r = requests.get(f"{REDIS_URL}/get/{key}", headers={"Authorization": f"Bearer {REDIS_TOKEN}"})
    return r.json().get("result") if r.status_code == 200 else None
def rsetex(key, seconds, value):
    requests.get(f"{REDIS_URL}/setex/{key}/{seconds}/{value}", headers={"Authorization": f"Bearer {REDIS_TOKEN}"})
def rincr(key):
    requests.get(f"{REDIS_URL}/incr/{key}", headers={"Authorization": f"Bearer {REDIS_TOKEN}"})
def rset(key, value):
    requests.get(f"{REDIS_URL}/set/{key}/{value}", headers={"Authorization": f"Bearer {REDIS_TOKEN}"})

def tg(method, payload):
    return requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/{method}", json=payload, timeout=9)
def reply(chat_id, text, parse_mode="Markdown"):
    tg("sendMessage", {"chat_id": chat_id, "text": text, "parse_mode": parse_mode})

def today_key(uid):
    return f"user:{uid}:uses:{datetime.date.today().isoformat()}"
def premium_key(uid):
    return f"user:{uid}:premium"

def has_premium(uid): return rget(premium_key(uid)) == "1"

def quota_ok(uid):
    if has_premium(uid): return True
    k = today_key(uid)
    uses = rget(k)
    if uses is None:
        now = datetime.datetime.now()
        tomorrow = now + datetime.timedelta(days=1)
        midnight = datetime.datetime.combine(tomorrow.date(), datetime.time.min)
        ttl = int((midnight - now).total_seconds())
        rsetex(k, ttl, "0"); uses = "0"
    return int(uses) < FREE_DAILY

def inc_quota(uid): rincr(today_key(uid))

# Telegram Payments
ENABLE_TG_PAY = os.getenv("ENABLE_TELEGRAM_PAYMENTS", "false").lower() == "true"
PROVIDER_TOKEN = os.getenv("PROVIDER_TOKEN", "")
PREMIUM_PRICE_EUR = int(os.getenv("PREMIUM_PRICE_EUR", "7"))
PREMIUM_TITLE = os.getenv("PREMIUM_TITLE", "Premium 30 days")
PREMIUM_DESCRIPTION = os.getenv("PREMIUM_DESCRIPTION", "30‑day pass: unlimited prompts & priority")
PREMIUM_DAYS = int(os.getenv("PREMIUM_DAYS", "30"))

def set_premium(uid, days=PREMIUM_DAYS):
    ttl = int(days) * 24 * 60 * 60
    rsetex(premium_key(uid), ttl, "1")

def llm(prompt):
    headers = {"Authorization": f"Bearer {OPENAI_API_KEY}"}
    body = {
        "model": OPENAI_MODEL, "temperature": 0.7,
        "messages": [
            {"role":"system","content": SYSTEM_PROMPT},
            {"role":"user","content": prompt}
        ]
    }
    r = requests.post("https://api.openai.com/v1/chat/completions", json=body, headers=headers, timeout=9)
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"].strip()

def cmd_premium(chat_id):
    # Brand-forward premium pitch + inline Stripe button
    parts = []
    parts.append("💎 *Spacebotty Premium* — grow faster, publish more\n")
    parts.append("Unlimited prompts · Priority responses · Advanced templates\n\n")
    parts.append("⚡ *Two ways to upgrade:*\n")
    parts.append("1) **/buy** — In‑app 30‑day pass (€7)\n")
    if STRIPE_PAYMENT_LINK:
        parts.append("2) **Stripe** — Monthly subscription (€9)\n")
    text = "".join(parts)

    if STRIPE_PAYMENT_LINK:
        tg("sendMessage", {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "Markdown",
            "reply_markup": {
                "inline_keyboard": [[
                    {"text": "Open Stripe (€9 / month)", "url": STRIPE_PAYMENT_LINK}
                ]]
            }
        })
    else:
        reply(chat_id, text)

def cmd_redeem(chat_id, uid, args):
    code = (args[0] if args else "").strip()
    if not code: reply(chat_id, "Usage: /redeem <CODE>"); return
    if code == PREMIUM_CODE:
        set_premium(uid, PREMIUM_DAYS); reply(chat_id, "✅ Premium activated.")
    else: reply(chat_id, "❌ Invalid code.")

def cmd_buy(chat_id):
    if not ENABLE_TG_PAY or not PROVIDER_TOKEN:
        reply(chat_id, "In‑app payments not configured. Use /premium for alternatives.")
        return
    prices = [{"label": PREMIUM_TITLE, "amount": PREMIUM_PRICE_EUR * 100}]
    tg("sendInvoice", {
        "chat_id": chat_id, "title": PREMIUM_TITLE, "description": PREMIUM_DESCRIPTION,
        "payload": "premium-purchase-30d", "provider_token": PROVIDER_TOKEN,
        "currency": "EUR", "prices": prices, "need_name": False, "need_phone_number": False,
        "need_email": False, "is_flexible": False
    })

def handle_pre_checkout(pre_checkout_query):
    tg("answerPreCheckoutQuery", {"pre_checkout_query_id": pre_checkout_query["id"], "ok": True})

def handle_successful_payment(chat_id, uid):
    set_premium(uid, PREMIUM_DAYS)
    reply(chat_id, "🎉 Payment received! Premium activated for 30 days.")

def cmd_status(chat_id, uid):
    uses = rget(today_key(uid)) or "0"
    prem = "✅ active" if has_premium(uid) else "❌ not active"
    reply(chat_id, f"*Status*\nPremium: {prem}\nToday: {uses}/{FREE_DAILY}", "Markdown")

SYSTEM_PROMPT = "You are an English copywriter for secondhand marketplaces (Vinted/Subito/eBay). Short, persuasive, clear."

def cmd_presets(chat_id):
    reply(chat_id, "Presets (Secondhand):\n"
                   "/title Nike sneakers 42 barely used\n"
                   "/desc Zara jacket M, great condition, pickup in Parma\n"
                   "/optimize [paste your current listing]\n"
                   "/hashtags women winter clothing")

def cmd_start(chat_id):
    reply(chat_id, dedent(f"""
    🛍️ **Welcome to *Secondhand Seller AI***
    I help you write titles and descriptions that actually sell.

    💬 Commands:
    • /title → 5 click‑worthy titles
    • /desc → persuasive description
    • /optimize → rewrite your existing listing
    • /hashtags → 20 targeted hashtags

    🪙 {FREE} free prompts per day.
    Unlock everything → **/buy** (€7 / 30 days) or **/premium** (€9 / month).

    📦 Try /presets to see a live example.
    """.format(FREE=FREE_DAILY)))

def ensure_quota_or_block(chat_id, uid):
    if quota_ok(uid): return True
    reply(chat_id, dedent(f"""
    🕒 You’ve used your {FREE_DAILY} free prompts today.

    💎 Upgrade to *Premium* to sell faster:
    • SEO‑optimized titles
    • Persuasive copywriting
    • Auto‑generated hashtags

    👉 **/buy** (€7 / 30 days)  |  **/premium** (€9 / month)
    """))
    return False

def do_title(chat_id, uid, item):
    if not ensure_quota_or_block(chat_id, uid): return
    if not item: reply(chat_id, "Give me the item: /title Nike sneakers 42 barely used"); return
    prompt = dedent(f"""
    Create *5 click‑through optimized titles* for a secondhand listing.
    Rules: 60–70 chars; include brand/model, condition, size/color if relevant.
    Item: {item}
    """.format(item=item))
    reply(chat_id, llm(prompt)); inc_quota(uid)

def do_desc(chat_id, uid, details):
    if not ensure_quota_or_block(chat_id, uid): return
    if not details: reply(chat_id, "Provide details: /desc Zara jacket M, great condition, local pickup Parma"); return
    prompt = dedent(f"""
    Write a *sales description* with:
    - Benefit & value (1–2 sentences)
    - Honest condition & defects (bullets)
    - Specs/Sizing (bullets)
    - Shipping/Delivery suggestions
    Details: {details}
    """.format(details=details))
    reply(chat_id, llm(prompt)); inc_quota(uid)

def do_optimize(chat_id, uid, listing):
    if not ensure_quota_or_block(chat_id, uid): return
    if not listing: reply(chat_id, "Paste your listing: /optimize <text>"); return
    prompt = dedent(f"""
    Rewrite this listing to *maximize search & conversion* on Vinted/Subito/eBay.
    Improve title, first 2 paragraphs, and final bullets. Keep it truthful.
    Original listing: {listing}
    """.format(listing=listing))
    reply(chat_id, llm(prompt)); inc_quota(uid)

def do_hashtags(chat_id, uid, category):
    if not ensure_quota_or_block(chat_id, uid): return
    if not category: reply(chat_id, "Category? /hashtags men sneakers"); return
    prompt = dedent(f"""
    Generate *20 targeted hashtags* for secondhand marketplaces (mix mid-volume and long‑tail).
    Category: {category}
    """.format(category=category))
    reply(chat_id, llm(prompt)); inc_quota(uid)

class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        body = self.rfile.read(int(self.headers.get("content-length","0"))); update = json.loads(body.decode("utf-8"))
        if "pre_checkout_query" in update:
            handle_pre_checkout(update["pre_checkout_query"]); return self._ok()
        msg = update.get("message") or update.get("edited_message")
        if not msg: return self._ok()
        chat_id = msg["chat"]["id"]; uid = msg["from"]["id"]; text = msg.get("text","")
        if "successful_payment" in msg:
            handle_successful_payment(chat_id, uid); return self._ok()

        if text.startswith("/start"): cmd_start(chat_id)
        elif text.startswith("/premium"): cmd_premium(chat_id)
        elif text.startswith("/buy"): cmd_buy(chat_id)
        elif text.startswith("/status"): cmd_status(chat_id, uid)
        elif text.startswith("/presets"): cmd_presets(chat_id)
        elif text.startswith("/redeem"):
            parts = text.split(maxsplit=1); args = parts[1].split() if len(parts)>1 else []
            cmd_redeem(chat_id, uid, args)
        elif text.startswith("/title"): do_title(chat_id, uid, text.replace("/title","",1).strip())
        elif text.startswith("/desc"): do_desc(chat_id, uid, text.replace("/desc","",1).strip())
        elif text.startswith("/optimize"): do_optimize(chat_id, uid, text.replace("/optimize","",1).strip())
        elif text.startswith("/hashtags"): do_hashtags(chat_id, uid, text.replace("/hashtags","",1).strip())
        else: reply(chat_id, "Commands: /title /desc /optimize /hashtags /presets /status /premium /redeem /buy")
        self._ok()
    def do_GET(self): self._ok(); self.wfile.write(b"OK")
    def _ok(self): self.send_response(200); self.send_header("Content-Type","text/plain"); self.end_headers()
