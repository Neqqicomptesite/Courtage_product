#!/usr/bin/env bash
# Sauvegarde de nuit : base PostgreSQL (Supabase) + pièces jointes, gardées 30 jours sur le serveur.
set -euo pipefail
set -a; . /etc/oddo/env; set +a
DEST=/var/backups/oddo
STAMP=$(date +%Y-%m-%d_%H%M)
URL="${DATABASE_URL/postgresql+psycopg:/postgresql:}"
pg_dump --format=custom --no-owner --no-privileges --schema=public "$URL" -f "$DEST/base_$STAMP.dump"
tar -czf "$DEST/fichiers_$STAMP.tar.gz" -C /var/lib/oddo --exclude=logs . 2>/dev/null || true
find "$DEST" -type f -mtime +30 -delete
chown -R oddo:oddo "$DEST"
echo "Sauvegarde OK : $(ls -1 "$DEST" | wc -l) fichiers, $(du -sh "$DEST" | cut -f1)"
