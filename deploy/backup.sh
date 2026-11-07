#!/usr/bin/env bash
# Sauvegarde : chaque nuit (timer) et avant chaque mise à jour.
#  1. base PostgreSQL (pg_dump) + fichiers (pièces jointes, logos), sur le serveur, 30 jours ;
#  2. contrôle que la sauvegarde de la base est lisible (pg_restore --list) ;
#  3. copie CHIFFRÉE hors du serveur (Supabase Storage, compartiment privé « sauvegardes »),
#     pour ne pas tout perdre si le serveur disparaît. Clé : ODDO_SECRET_KEY (à garder aussi
#     hors du serveur : sans elle, les copies sont illisibles) ;
#  4. état écrit dans /var/lib/oddo/backup-status.json : /api/health le signale (503) si la
#     dernière sauvegarde réussie a plus de 36 h, ce qui déclenche l'alerte de surveillance.
set -euo pipefail
set -a; . /etc/oddo/env; set +a
export PGSSLMODE=require   # connexion chiffrée vers Supabase
DEST=/var/backups/oddo
STATUS=/var/lib/oddo/backup-status.json
STAMP=$(date +%Y-%m-%d_%H%M)
URL="${DATABASE_URL/postgresql+psycopg:/postgresql:}"
fail() { printf '{"ok": false, "ts": "%s", "error": "%s"}\n' "$(date -Is)" "$1" > "$STATUS"; chown oddo:oddo "$STATUS"; echo "ÉCHEC : $1" >&2; exit 1; }
trap 'fail "erreur ligne $LINENO"' ERR

DB="$DEST/base_$STAMP.dump"; FILES="$DEST/fichiers_$STAMP.tar.gz"
pg_dump --format=custom --no-owner --no-privileges --schema=public "$URL" -f "$DB"
pg_restore --list "$DB" > /dev/null                      # la sauvegarde se relit
tar -czf "$FILES" -C /var/lib/oddo --exclude=./logs --exclude=./backup-status.json .
find "$DEST" -type f -mtime +30 -delete

OFFSITE=false
if [ -n "${SUPABASE_URL:-}" ] && [ -n "${SUPABASE_SECRET_KEY:-}" ]; then
  up() {  # $1 = fichier local, $2 = nom distant
    local enc; enc="$(mktemp)"
    openssl enc -aes-256-cbc -pbkdf2 -iter 200000 -salt -pass env:ODDO_SECRET_KEY -in "$1" -out "$enc"
    local code
    for auth in "" "Authorization: Bearer $SUPABASE_SECRET_KEY"; do
      code=$(curl -s -o /dev/null -w '%{http_code}' -X POST "$SUPABASE_URL/storage/v1/object/sauvegardes/$2" \
        -H "apikey: $SUPABASE_SECRET_KEY" ${auth:+-H "$auth"} -H "x-upsert: true" \
        -H "Content-Type: application/octet-stream" --data-binary @"$enc") || code=000
      [ "$code" = "200" ] && break
    done
    rm -f "$enc"; [ "$code" = "200" ]
  }
  for auth in "" "Authorization: Bearer $SUPABASE_SECRET_KEY"; do   # compartiment privé (créé une fois)
    curl -s -o /dev/null -X POST "$SUPABASE_URL/storage/v1/bucket" -H "apikey: $SUPABASE_SECRET_KEY" ${auth:+-H "$auth"} \
      -H "Content-Type: application/json" -d '{"id":"sauvegardes","name":"sauvegardes","public":false}' || true
  done
  if up "$DB" "base_$STAMP.dump.enc" && up "$FILES" "fichiers_$STAMP.tar.gz.enc"; then OFFSITE=true; fi
fi
trap - ERR
chown -R oddo:oddo "$DEST"
printf '{"ok": true, "ts": "%s", "offsite": %s, "base": "%s"}\n' "$(date -Is)" "$OFFSITE" "$(basename "$DB")" > "$STATUS"
chown oddo:oddo "$STATUS"
echo "Sauvegarde OK ($(du -sh "$DEST" | cut -f1) sur le serveur) ; copie hors serveur : $OFFSITE"
