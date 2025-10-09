# Spacebotty — Telegram + OpenAI Bot (Serverless on Vercel)

A simple Telegram bot deployed as Vercel Serverless Functions.
Generates LinkedIn-style content via OpenAI.

## Commands
/start — shows the inline menu  
/openers <topic> — generates 10 hooks  
/post <topic> — generates a full post  

## Deployment
- Push this folder to GitHub
- Import to Vercel (project root = this folder)
- Add the Environment Variables below
- Deploy!

## Telegram Webhook
After deploy:
https://api.telegram.org/bot<TOKEN>/setWebhook?url=https://<YOUR_DOMAIN>/api/telegram

