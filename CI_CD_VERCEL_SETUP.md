# CI/CD with GitHub Actions and Vercel
## Required GitHub Secrets
- `VERCEL_TOKEN` — from Vercel (Account Settings → Tokens)
- `VERCEL_ORG_ID` — Organization ID from Vercel
- `VERCEL_PROJECT_ID_<SLUG>` — one per app. `<SLUG>` is uppercased package name with non-alphanumerics replaced by `_`.
  - Example: for package `web-app`, create `VERCEL_PROJECT_ID_WEB_APP`.

## How to link apps
1. Create a Vercel project for each app path below and copy its `PROJECT_ID`:

2. Add the secrets in GitHub: *Settings → Secrets and variables → Actions*.
3. Push to `main`/`master`: the `Deploy to Vercel` workflow will deploy Preview and Production automatically.
