#!/usr/bin/env bash
set -euo pipefail
echo 'Bootstrapping monorepo...'
echo 'Using package manager: npm'
npm -v
npm install
echo 'Copying .env examples (if any) ...'
cp -n 'apps/linkedin/.env.example' 'apps/linkedin/.env' || true
cp -n 'apps/creators/.env.example' 'apps/creators/.env' || true
cp -n 'apps/secondhand/.env.example' 'apps/secondhand/.env' || true
echo 'No apps detected. Explore packages to start manually.'