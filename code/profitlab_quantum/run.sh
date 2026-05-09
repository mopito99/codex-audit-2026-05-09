#!/bin/bash
cd /root/srv/profitlab_quantum
if [ -f .env ]; then
  export $(grep -v '^#' .env | xargs)
fi
./venv/bin/uvicorn web.main:app --host 0.0.0.0 --port 8001

