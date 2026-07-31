#!/bin/bash
cd /Users/ivansemke/Desktop/book-bot

# Load secrets from .env (not committed to git)
set -a
[ -f .env ] && . ./.env
set +a

# Kill existing processes
pkill -f "ngrok" 2>/dev/null
pkill -f "python3 main.py" 2>/dev/null
sleep 2

# Start ngrok with static domain
/usr/bin/python3 -c "
import os
from pyngrok import ngrok, conf
conf.get_default().auth_token = os.environ['NGROK_TOKEN']
ngrok.connect(8080, domain='relearn-whiff-pusher.ngrok-free.dev')
import time; time.sleep(99999)
" &
sleep 3

# Start bot
PUBLIC_URL=https://relearn-whiff-pusher.ngrok-free.dev exec /usr/bin/python3 main.py
