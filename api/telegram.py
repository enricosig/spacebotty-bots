# api/telegram.py
import os, json, datetime, requests, traceback
from textwrap import dedent
from urllib.parse import quote_plus
from http.server import BaseHTTPRequestHandler

def log(*args):
    try: print(*args, flush=True)
    except: pass

# ===== ENV =====
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "https://spacebotty-bots.vercel.app")

REDIS_URL = os.getenv("UPSTASH_REDIS_REST_URL")
REDIS_TOKEN = os.getenv("UPSTASH_REDIS_REST_TOKEN")

ENABLE_TG_PAY = os.getenv("ENABLE_TELEGRAM_PAYMENTS", "false").lower() == "true"
PROVIDER_TOKEN = os.getenv("PROVIDER_TOKEN", "")

FREE_DAILY = int(os.getenv("FREE_DAILY", "2"))
PREMIUM_CODE = os.getenv("PREMIUM_CODE", "VIP-2025")

DAILY_PRICE_EUR = int(os.getenv("DAILY_PRICE_EUR", "5"))
DAILY_DAYS = int(os.getenv("DAILY_DAYS", "1"))
PREMIUM_PRICE_EUR = int(os.getenv("PREMIUM_PRICE_EUR", "9"))
PREMIUM_DAYS = int(os.getenv("PREMIUM_DAYS", "30"))

STRIPE_PAYMENT_LINK = os.getenv("STRIPE_PAYMENT_LINK", "")

# ===== Upstash (REST) =====
def _h(): return {"Authorization": f"Bearer {REDIS_TOKEN}"} if REDIS_TOKEN else {}
def rget(k):
    if not REDIS_URL or not REDIS_TOKEN: return None
    try:
        r = requests.get(f"{REDIS_URL}/get/{k}", headers=_h(), timeout=8)
        return r.json().get("result") if r.status_code == 200 else None
    except Exception as e: log("rget", repr(e)); return None
def rsetex(k, s, v):
    if not REDIS_URL or not REDIS_TOKEN: return
    try: requests.get(f"{REDIS_URL}/setex/{k}/{s}/{v}", headers=_h(), timeout=8)
    except Exception as e: log("rsetex", repr(e))
def rset(k, v):
    if not REDIS_URL or not REDIS_TOKEN: return
    try: requests.get(f"{REDIS_URL}/set/{k}/{v}", headers=_h(), timeout=8)
    except Exception as e: log("rset", repr(e))
def rincr(k):
    if not REDIS_URL or not REDIS_TOKEN: return
    try: requests.get(f"{REDIS_URL}/incr/{k}", headers=_h(), timeout=8)
    except Exception as e: log("rincr", repr(e))

def today_key(uid): return f"user:{uid}:uses:{datetime.date.today().isoformat()}"
def premium_key(uid): return f"user:{uid}:premium"
def li_token_key(uid): return f"li:{uid}:access"
def li_profile_key(uid): return f"li:{uid}:person"

def has_premium(uid): return rget(premium_key(uid)) == "1"

def ensure_day_counter(uid):
    k = today_key(uid); uses = rget(k)
    if uses is None:
        now = datetime.datetime.now()
        ttl = int((datetime.datetime.combine((now+datetime.timedelta(days=1)).date(), datetime.time.min) - now).total_seconds())
        rsetex(k, ttl, "0")
        return 0
    try: return int(uses)
    except: return 0

def quota_ok(uid):
    if has_premium(uid): return True
    return ensure_day_counter(uid) < FREE_DAILY

def inc_quota(uid): rincr(today_key(uid))
def set_premium_days(uid, days): rsetex(premium_key(uid), int(days)*86400, "1")

# ===== Telegram =====
def tg(method, payload):
    if not BOT_TOKEN: log("TOKEN missing"); return None
    try: return requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/{method}", json=payload, timeout=15)
    except Exception as e: log("tg", repr(e)); return None

def reply(chat_id, text, parse_mode="Markdown", keyboard=None):
    payload = {"chat_id": chat_id, "text": text, "parse_mode": parse_mode}
    if keyboard: payload["reply_markup"] = keyboard
    try: tg("sendMessage", payload)
    except Exception as e: log("sendMessage", repr(e))

# ===== OpenAI =====
SYSTEM_PROMPT = "You are an English content strategist for LinkedIn. Return only the requested content, clear and scannable."
def _temperature(): return 1 if "gpt-5-mini" in (OPENAI_MODEL or "") else 0.7

def llm(prompt):
    if not OPENAI_API_KEY:
        return "⚠️ OPENAI_API_KEY not set."
    body = {
        "model": OPENAI_MODEL,
        "temperature": _temperature(),
        "messages": [
            {"role":"system","content": SYSTEM_PROMPT},
            {"role":"user","content": prompt}
        ]
    }
    try:
        r = requests.post("https://api.openai.com/v1/chat/completions",
                          json=body, headers={"Authorization": f"Bearer {OPENAI_API_KEY}"}, timeout=25)
        if r.status_code >= 400:
            try: err = r.json()
            except: err = {"error": r.text}
            msg = (err.get("error") or {}).get("message", "").lower()
            if "temperature" in msg:
                body.pop("temperature", None)
                r2 = requests.post("https://api.openai.com/v1/chat/completions",
                                   json=body, headers={"Authorization": f"Bearer {OPENAI_API_KEY}"}, timeout=25)
                if r2.status_code == 200:
                    return r2.json()["choices"][0]["message"]["content"].strip()
            if "quota" in msg or "insufficient_quota" in str(err):
                return "⚠️ OpenAI quota exceeded for this key. Try again later."
            if r.status_code == 404:
                return "⚠️ Model not found for this account. Set OPENAI_MODEL to an available model and redeploy."
            return "⚠️ OpenAI request failed. Please try later."
        return r.json()["choices"][0]["message"]["content"].strip()
    except Exception:
        return "⚠️ OpenAI request failed. Please try again."

# ===== LinkedIn helpers (USANO /api/oauth/* e /api/post*) =====
def li_connected(uid):
    return bool(rget(li_token_key(uid)) and rget(li_profile_key(uid)))

def connect_button(uid):
    url = f"{PUBLIC_BASE_URL}/api/oauth/start?uid={uid}"
    return {"inline_keyboard":[[{"text":"🔗 Connect LinkedIn","url": url}]]}

def btn_post_text(uid, text):
    # testo puro: handler /api/post
    url = f"{PUBLIC_BASE_URL}/api/post?uid={uid}&text={quote_plus(text)}"
    return {"inline_keyboard":[[{"text":"📤 Post on LinkedIn","url": url}]]}

def btn_post_image(uid, text, image_url):
    # singola immagine: handler /api/post_media
    url = f"{PUBLIC_BASE_URL}/api/post_media?uid={uid}&image_url={quote_plus(image_url)}&text={quote_plus(text)}"
    return {"inline_keyboard":[[{"text":"📸 Post with image","url": url}]]}

def btn_post_album(uid, text, image_urls, captions=None):
    # più immagini: handler /api/post_media_multi
    qs = "&".join([f"image_url={quote_plus(u)}" for u in image_urls])
    if captions:
        qs += "&" + "&".join([f"image_caption={quote_plus(c)}" for c in captions])
    url = f"{PUBLIC_BASE_URL}/api/post_media_multi?uid={uid}&{qs}&text={quote_plus(text)}"
    return {"inline_keyboard":[[{"text":"🖼️ Post album","url": url}]]}

# ===== Commands =====
def cmd_start(chat_id):
    reply(chat_id, dedent(f"""
    🚀 **Welcome to *LinkedIn Growth AI***
    Create hooks, posts, comments & content plans that convert.

    ⚡ Commands:
    • /openers → 10 viral openers
    • /post → full post
    • /postimg → post + one image  (use: /postimg Topic | https://img...)
    • /postimgs → post + multiple images
        - Quick: /postimgs Topic | https://img1 ... https://imgN
        - Captions: /postimgs Topic || url1::caption1 || url2::caption2 ...
    • /comment → sharp comments
    • /contentplan → 7-day plan
    • /connect → link your LinkedIn
    • /status, /presets, /premium, /buy

    🆓 Free: *{FREE_DAILY} prompts/day*
    💎 Premium: Daily €{DAILY_PRICE_EUR} (24h) • Monthly €{PREMIUM_PRICE_EUR} (30d)
    """))

def cmd_connect(chat_id, uid):
    reply(chat_id, "Link your LinkedIn account to one-click post:", keyboard=connect_button(uid))

def cmd_presets(chat_id):
    reply(chat_id, "Presets (LinkedIn):\n"
                   "/openers grow your LinkedIn audience as a PM\n"
                   "/post case study: reduce churn in B2B SaaS\n"
                   "/postimg case study with image | https://...\n"
                   "/postimgs carousel tips | https://.../1.jpg https://.../2.png\n"
                   "/comment personal branding for engineers\n"
                   "/contentplan AI consultant in B2B")

def cmd_status(chat_id, uid):
    uses = ensure_day_counter(uid)
    prem = "✅ active" if has_premium(uid) else "❌ not active"
    li = "✅ connected" if li_connected(uid) else "❌ not connected"
    reply(chat_id, f"*Status*\nPremium: {prem}\nToday: {uses}/{FREE_DAILY}\nLinkedIn: {li}")

def ensure_quota_or_block(chat_id, uid):
    if quota_ok(uid): return True
    kb = {"inline_keyboard":[
        [{"text": f"💎 Daily Pass (€{DAILY_PRICE_EUR})", "callback_data":"buy_daily"}],
        [{"text": f"🚀 Monthly (€{PREMIUM_PRICE_EUR})", "callback_data":"buy_monthly"}]
    ]}
    reply(chat_id, dedent(f"""
    ⚠️ You've used your {FREE_DAILY} free prompts today.

    Upgrade to *Premium*:
    • Daily Pass: {DAILY_DAYS} day — unlimited prompts
    • Monthly: {PREMIUM_DAYS} days — unlimited prompts

    Choose a plan below ↓
    """), keyboard=kb)
    return False

def cmd_premium(chat_id):
    text = ("💎 *Spacebotty Premium* — grow faster, publish more\n"
            "Unlimited prompts · Priority responses · Advanced templates\n\n"
            f"🪙 *Plans*\n• Daily: €{DAILY_PRICE_EUR} ({DAILY_DAYS} day)\n"
            f"• Monthly: €{PREMIUM_PRICE_EUR} ({PREMIUM_DAYS} days)\n")
    kb = {"inline_keyboard":[
        [{"text": f"💎 Daily Pass (€{DAILY_PRICE_EUR})", "callback_data":"buy_daily"}],
        [{"text": f"🚀 Monthly (€{PREMIUM_PRICE_EUR})", "callback_data":"buy_monthly"}]
    ]}
    if STRIPE_PAYMENT_LINK:
        kb["inline_keyboard"].append([{"text":"Open Stripe (€9 / month)", "url": STRIPE_PAYMENT_LINK}])
    reply(chat_id, text, keyboard=kb)

def cmd_redeem(chat_id, uid, args):
    code = (args[0] if args else "").strip()
    if not code: reply(chat_id, "Usage: /redeem <CODE>"); return
    if code == PREMIUM_CODE:
        set_premium_days(uid, PREMIUM_DAYS); reply(chat_id, "✅ Premium activated.")
    else:
        reply(chat_id, "❌ Invalid code.")

# ===== Payments =====
def send_invoice(chat_id, title, desc, euros, payload):
    if not ENABLE_TG_PAY or not PROVIDER_TOKEN:
        reply(chat_id, "In-app payments not configured. Use /premium for alternatives.")
        return
    tg("sendInvoice", {
        "chat_id": chat_id,
        "title": title,
        "description": desc,
        "payload": payload,
        "provider_token": PROVIDER_TOKEN,
        "currency": "EUR",
        "prices": [{"label": title, "amount": euros * 100}],
        "is_flexible": False
    })

def cmd_buy(chat_id):
    kb = {"inline_keyboard":[
        [{"text": f"💎 Daily Pass (€{DAILY_PRICE_EUR})", "callback_data":"buy_daily"}],
        [{"text": f"🚀 Monthly (€{PREMIUM_PRICE_EUR})", "callback_data":"buy_monthly"}]
    ]}
    reply(chat_id, "Choose your premium plan:", keyboard=kb)

def cmd_buy_plan(chat_id, uid, plan):
    if plan == "daily":
        send_invoice(chat_id, f"Daily Premium ({DAILY_DAYS} day)",
                     f"Unlimited prompts for {DAILY_DAYS} day", DAILY_PRICE_EUR, "premium-daily")
    else:
        send_invoice(chat_id, f"Monthly Premium ({PREMIUM_DAYS} days)",
                     f"Unlimited prompts for {PREMIUM_DAYS} days", PREMIUM_PRICE_EUR, "premium-monthly")

def handle_pre_checkout(pre_checkout_query):
    tg("answerPreCheckoutQuery", {"pre_checkout_query_id": pre_checkout_query["id"], "ok": True})

def handle_successful_payment(chat_id, uid, payload):
    if payload == "premium-daily":
        set_premium_days(uid, DAILY_DAYS); reply(chat_id, f"🎉 Daily Pass active for {DAILY_DAYS} day.")
    else:
        set_premium_days(uid, PREMIUM_DAYS); reply(chat_id, f"🎉 Premium active for {PREMIUM_DAYS} days.")

# ===== Generators =====
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
    post_text = llm(prompt)
    kb = btn_post_text(uid, post_text) if li_connected(uid) else connect_button(uid)
    reply(chat_id, post_text, keyboard=kb); inc_quota(uid)

def do_postimg(chat_id, uid, payload):
    parts = [p.strip() for p in payload.split("|", 1)]
    if len(parts) != 2:
        reply(chat_id, "Format: /postimg Topic | https://example.com/image.jpg"); return
    topic, image_url = parts
    if not ensure_quota_or_block(chat_id, uid): return
    prompt = dedent(f"""Write a *LinkedIn post* optimized for an accompanying image.
- Headline (1 line)
- Body: 5–8 short lines
- CTA (1 line)
Topic: {topic}""")
    post_text = llm(prompt)
    kb = btn_post_image(uid, post_text, image_url) if li_connected(uid) else connect_button(uid)
    reply(chat_id, post_text + "\n\n(Attached image: " + image_url + ")", keyboard=kb); inc_quota(uid)

def _parse_album_payload(payload):
    if "||" in payload:
        topic, rest = [p.strip() for p in payload.split("||", 1)]
        pairs = []
        for seg in rest.split("||"):
            seg = seg.strip()
            if not seg: continue
            if "::" in seg:
                url, cap = seg.split("::", 1)
                pairs.append((url.strip(), cap.strip()))
            else:
                pairs.append((seg.strip(), None))
        return topic, pairs
    topic, urls_blob = [p.strip() for p in payload.split("|", 1)]
    urls = [u for u in urls_blob.split() if u.startswith("http")]
    return topic, [(u, None) for u in urls]

def do_postimgs(chat_id, uid, payload):
    topic, pairs = _parse_album_payload(payload)
    image_urls = [u for (u, _) in pairs if u.startswith("http")]
    if len(image_urls) < 2:
        reply(chat_id, "Please provide at least *two* image URLs.\nTip: /postimgs Topic | https://img1 https://img2"); return
    if len(image_urls) > 9:
        image_urls = image_urls[:9]

    if not ensure_quota_or_block(chat_id, uid): return

    post_prompt = dedent(f"""Write a *LinkedIn carousel-style post* that pairs with multiple images.
- Hook (1 line)
- 5–8 short lines (carousel tips / steps)
- CTA (1 line)
Topic: {topic}""")
    post_text = llm(post_prompt)

    provided_caps = [cap for (_, cap) in pairs]
    if any(c is None for c in provided_caps):
        n = len(image_urls)
        caps_prompt = dedent(f"""Create {n} short (max 10 words) slide captions for a LinkedIn image carousel.
Keep them actionable and non-repetitive. Topic: {topic}
Return each caption on its own line, no numbering.""")
        caps_text = llm(caps_prompt)
        auto_caps = [c.strip(" -•\t") for c in caps_text.splitlines() if c.strip()]
        if len(auto_caps) < n: auto_caps += [""]*(n-len(auto_caps))
        if len(auto_caps) > n: auto_caps = auto_caps[:n]
        captions = [pc if pc is not None else auto_caps[i] for i, pc in enumerate(provided_caps)]
    else:
        captions = provided_caps

    kb = btn_post_album(uid, post_text, image_urls, captions) if li_connected(uid) else connect_button(uid)
    preview = "\n".join([f"{i+1}) {image_urls[i]} — {captions[i]}" for i in range(len(image_urls))])
    reply(chat_id, post_text + "\n\nSlides:\n" + preview, keyboard=kb); inc_quota(uid)

# (placeholder simple versions)
def do_comment(chat_id, uid, topic):
    if not ensure_quota_or_block(chat_id, uid): return
    if not topic: reply(chat_id, "Give me a topic: /comment product-led growth"); return
    prompt = f"Write 5 concise LinkedIn comments (1-2 lines) on: {topic}"
    reply(chat_id, llm(prompt)); inc_quota(uid)

def do_contentplan(chat_id, uid, topic):
    if not ensure_quota_or_block(chat_id, uid): return
    if not topic: reply(chat_id, "Give me a niche: /contentplan AI for B2B sales"); return
    prompt = f"Create a 7-day LinkedIn content plan for: {topic}. Each day: title + 2 bullets."
    reply(chat_id, llm(prompt)); inc_quota(uid)

# ===== HTTP handler =====
class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        try:
            body = self.rfile.read(int(self.headers.get("content-length","0")))
            update = json.loads(body.decode("utf-8"))

            if "pre_checkout_query" in update:
                tg("answerPreCheckoutQuery", {"pre_checkout_query_id": update["pre_checkout_query"]["id"], "ok": True})
                return self._ok()

            cb = update.get("callback_query")
            if cb:
                data = cb.get("data","")
                chat_id = cb["message"]["chat"]["id"]
                uid = cb["from"]["id"]
                if data == "buy_daily": send_invoice(chat_id, f"Daily Premium ({DAILY_DAYS} day)",
                                                     f"Unlimited prompts for {DAILY_DAYS} day", DAILY_PRICE_EUR, "premium-daily")
                elif data == "buy_monthly": send_invoice(chat_id, f"Monthly Premium ({PREMIUM_DAYS} days)",
                                                         f"Unlimited prompts for {PREMIUM_DAYS} days", PREMIUM_PRICE_EUR, "premium-monthly")
                tg("answerCallbackQuery", {"callback_query_id": cb["id"], "text": "Processing..."})
                return self._ok()

            msg = update.get("message") or update.get("edited_message")
            if not msg: return self._ok()

            chat_id = msg["chat"]["id"]; uid = msg["from"]["id"]; text = msg.get("text","")

            if "successful_payment" in msg:
                payload = msg["successful_payment"]["invoice_payload"]
                handle_successful_payment(chat_id, uid, payload); return self._ok()

            if   text.startswith("/start"):        cmd_start(chat_id)
            elif text.startswith("/connect"):      cmd_connect(chat_id, uid)
            elif text.startswith("/premium"):      cmd_premium(chat_id)
            elif text.startswith("/buy"):          cmd_buy(chat_id)
            elif text.startswith("/status"):       cmd_status(chat_id, uid)
            elif text.startswith("/presets"):      cmd_presets(chat_id)
            elif text.startswith("/redeem"):
                parts = text.split(maxsplit=1); args = parts[1].split() if len(parts)>1 else []
                cmd_redeem(chat_id, uid, args)
            elif text.startswith("/openers"):      do_openers(chat_id, uid, text.replace("/openers","",1).strip())
            elif text.startswith("/postimgs"):     do_postimgs(chat_id, uid, text.replace("/postimgs","",1).strip())
            elif text.startswith("/postimg"):      do_postimg(chat_id, uid, text.replace("/postimg","",1).strip())
            elif text.startswith("/post"):         do_post(chat_id, uid, text.replace("/post","",1).strip())
            elif text.startswith("/comment"):      do_comment(chat_id, uid, text.replace("/comment","",1).strip())
            elif text.startswith("/contentplan"):  do_contentplan(chat_id, uid, text.replace("/contentplan","",1).strip())
            else:
                reply(chat_id, "Commands: /openers /post /postimg /postimgs /comment /contentplan /presets /status /connect /premium /redeem /buy")
            self._ok()
        except Exception:
            self._ok()

    def do_GET(self):
        self._ok()
        try: self.wfile.write(b"OK")
        except: pass

    def _ok(self):
        self.send_response(200); self.send_header("Content-Type","text/plain"); self.end_headers()
