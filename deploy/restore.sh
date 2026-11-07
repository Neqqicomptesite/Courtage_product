#!/usr/bin/env bash
# Restauration (à lancer à la main, en root, dans la console Hetzner).
#   restore.sh                          liste les sauvegardes disponibles
#   restore.sh base_AAAA-MM-JJ_HHMM.dump [fichiers_….tar.gz]
# Arrête l'appli, remplace le contenu de la base par la sauvegarde (schéma public), remet
# les fichiers si demandé, puis redémarre. Une sauvegarde de l'état actuel est faite avant.
set -euo pipefail
set -a; . /etc/oddo/env; set +a
export PGSSLMODE=require   # connexion chiffrée vers Supabase
# le client PostgreSQL le plus récent installé (pas l'enrobage pg_wrapper d'Ubuntu)
PGBIN=$(ls -d /usr/lib/postgresql/*/bin 2>/dev/null | sort -V | tail -1)
[ -n "$PGBIN" ] && export PATH="$PGBIN:$PATH"
DEST=/var/backups/oddo
URL="${DATABASE_URL/postgresql+psycopg:/postgresql:}"
if [ $# -eq 0 ]; then ls -1t "$DEST"; exit 0; fi
DB="$DEST/$1"; [ -f "$DB" ] || { echo "Introuvable : $DB"; exit 1; }
pg_restore --list "$DB" > /dev/null
read -r -p "Remplacer TOUTE la base par $1 ? Tapez RESTAURER : " ok
[ "$ok" = "RESTAURER" ] || { echo "Annulé."; exit 1; }
/usr/local/sbin/backup.sh || echo "(sauvegarde préalable impossible, on continue)"
systemctl stop oddo.service
pg_restore --clean --if-exists --no-owner --no-privileges --single-transaction -d "$URL" "$DB"
if [ $# -ge 2 ]; then tar -xzf "$DEST/$2" -C /var/lib/oddo && chown -R oddo:oddo /var/lib/oddo; fi
systemctl start oddo.service
echo "Restauration terminée. Vérifiez l'appli dans le navigateur."
