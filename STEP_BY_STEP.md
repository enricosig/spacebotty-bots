# Step-by-step Guide (EN)

## 1) Prepare
- Create 3 Telegram bots with @BotFather and save their tokens.
- Get an **OpenAI API key**.
- (Optional) Set up **Telegram Payments** with a provider (BotFather → Payments) to get a `PROVIDER_TOKEN`.
- Add **Upstash Redis** from Vercel Integrations and copy REST URL and TOKEN.

## 2) Create 3 Vercel projects (one per app)
Import this repo 3 times and set the **Root Directory** to:
- `apps/linkedin`
- `apps/creators`
- `apps/secondhand`

## 3) Environment variables (each project)
- `TELEGRAM_BOT_TOKEN` = token of the *specific* bot
- `OPENAI_API_KEY` = your key
- `OPENAI_MODEL` = `gpt-5-mini`

Freemium/Premium:
- `FREE_DAILY` = `3`
- `PREMIUM_CODE` = `VIP-2025` (change as you like)
- `STRIPE_PAYMENT_LINK` = your Stripe Payment Link (€9/month) — optional

Telegram Payments (in‑app pass):
- `ENABLE_TELEGRAM_PAYMENTS` = `true`
- `PROVIDER_TOKEN` = from BotFather → Payments
- `PREMIUM_PRICE_EUR` = `7`
- `PREMIUM_TITLE` = `Premium 30 days`
- `PREMIUM_DESCRIPTION` = `30‑day pass: unlimited prompts & priority`
- `PREMIUM_DAYS` = `30`

Upstash Redis:
- `UPSTASH_REDIS_REST_URL`
- `UPSTASH_REDIS_REST_TOKEN`

## 4) Deploy + Webhooks
- Deploy each project in Vercel.
- Register webhooks with the included script:
```bash
export LINKEDIN_BOT_TOKEN="..."
export CREATORS_BOT_TOKEN="..."
export SECONDHAND_BOT_TOKEN="..."

export LINKEDIN_URL="https://linkedin-<your>.vercel.app"
export CREATORS_URL="https://creators-<your>.vercel.app"
export SECONDHAND_URL="https://secondhand-<your>.vercel.app"

chmod +x scripts/setup.sh
./scripts/setup.sh
```

## 5) Test in Telegram
- `/start` welcome screen (EN)
- LinkedIn: `/openers grow your LinkedIn audience as a PM`
- Creators: `/hooks TikTok ideas for beginners`
- Secondhand: `/title Nike Air Max 42, barely used`
- `/status` to see premium & daily usage
- `/presets` for ready prompts
- `/buy` (if payments configured) → activates premium for 30 days

## 6) Stripe monthly subscription (optional)
Create a product (€9/month), generate a **Payment Link**, and set `STRIPE_PAYMENT_LINK`. Then `/premium` shows it alongside `/buy`.

## 7) Bot bios & commands
Use the English `BOTFATHER_BIOS.md` you created to set `/setdescription`, `/setabouttext`, `/setcommands` in @BotFather.
