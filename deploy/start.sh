#!/bin/bash
# Runs the API and the WhatsApp bridge; if either exits, the container exits and Docker restarts it.
set -u
cd /app/backend
.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000 --proxy-headers &
node /app/wa/index.js &
trap 'kill 0' TERM INT
wait -n
code=$?
echo "a process exited ($code) — stopping container"
kill 0
exit $code
