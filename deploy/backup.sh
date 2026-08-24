#!/usr/bin/env bash
# Ежедневный бэкап SQLite (добавить строкой в cs-daily-backup или cron 04:40)
set -euo pipefail
SRC=/srv/cod_agent/var/cod.db
DST=/srv/backups/cod_agent
mkdir -p "$DST"
sqlite3 "$SRC" ".backup '$DST/cod-$(date +%F).db'"
gzip -f "$DST/cod-$(date +%F).db"
find "$DST" -name 'cod-*.db.gz' -mtime +30 -delete
