#!/usr/bin/env bash
# Застосувати правки, зроблені прямо на сервері: тести → рестарт → коміт у GitHub.
# Використання:  bash deploy/apply.sh "Саша" "що змінили"
set -euo pipefail
cd /srv/cod_agent
WHO="${1:-Хтось}"; MSG="${2:-правки з сервера}"

echo '▶ тести'
venv/bin/python -m pytest -q tests || { echo '❌ тести червоні — нічого не чіпаю'; exit 1; }

echo '▶ перевірка offer.yaml'
venv/bin/python -c "from core.offer import load_offer; load_offer('offer.yaml'); print('offer ok')"

echo '▶ рестарт бота'
systemctl restart cod-agent
sleep 6
systemctl is-active --quiet cod-agent || { echo '❌ бот не піднявся — дивись journalctl -u cod-agent -n 30'; exit 1; }

echo '▶ коміт у GitHub'
git add -A
if git diff --cached --quiet; then
  echo 'нічого не змінилось'
else
  git -c user.name="$WHO" -c user.email="$(echo $WHO | tr 'А-Яа-я ' 'a-z-')@cod-agent.local" commit -q -m "$MSG"
  git push -q origin main && echo '✅ запушено'
fi
echo '✅ готово — бот працює з новим кодом'
