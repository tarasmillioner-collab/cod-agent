#!/usr/bin/env bash
# Деплой cod-agent на VPS (rsync → venv → systemd). config.env и var/*.db на сервере не трогаем.
set -euo pipefail
HOST="${HOST:-hostinger-studio}"
DEST="${DEST:-/srv/cod_agent}"
UNIT="cod-agent"
HERE="$(cd "$(dirname "$0")/.." && pwd)"

echo "▶ pre-flight: offer.yaml + tests"
"$HERE/.venv/bin/python" -c "from core.offer import load_offer; load_offer('$HERE/offer.yaml'); print('offer ok')"
"$HERE/.venv/bin/python" -m pytest -q "$HERE/tests" >/dev/null && echo "tests ok"

echo "▶ rsync → $HOST:$DEST"
ssh "$HOST" "mkdir -p $DEST/var"
rsync -az --delete \
  --exclude '.venv/' --exclude 'venv/' --exclude '__pycache__/' --exclude '*.pyc' --exclude '.git/' \
  --exclude 'var/' --exclude 'config.env' --exclude '.pytest_cache/' \
  "$HERE/" "$HOST:$DEST/"

echo "▶ config.env (только если нет на сервере)"
ssh "$HOST" "test -f $DEST/config.env || { cp $DEST/config.env.example $DEST/config.env; chmod 600 $DEST/config.env; echo '!! заполни $DEST/config.env'; }"

echo "▶ venv + deps"
ssh "$HOST" "cd $DEST && (test -d venv || python3 -m venv venv) && venv/bin/pip install -q -r requirements.txt"

echo "▶ systemd"
ssh "$HOST" "cp $DEST/deploy/$UNIT.service /etc/systemd/system/ && systemctl daemon-reload && systemctl enable $UNIT >/dev/null && systemctl restart $UNIT && sleep 2 && systemctl is-active $UNIT && tail -n 5 /var/log/cod-agent.log"
echo "✅ done"
