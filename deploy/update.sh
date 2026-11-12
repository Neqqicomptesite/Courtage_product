#!/usr/bin/env bash
# Mise à jour automatique (timer systemd, toutes les 15 min, en root).
#
# Règles (revue externe, point 3) :
#  - seulement la branche « production » (poussée après les tests), jamais « main » ;
#  - seulement HORS des heures d'envoi (20 h – 7 h, heure du Maroc), pour ne jamais couper
#    un envoi en cours ; pour forcer une mise à jour urgente : touch /etc/oddo/update-now ;
#  - sauvegarde de la base AVANT d'appliquer (les migrations s'appliquent au redémarrage) ;
#  - le code appartient à root : l'appli (utilisateur oddo) ne peut pas le modifier ;
#  - les fichiers système (services, ce script, la sauvegarde) ne sont PAS réinstallés
#    automatiquement : seulement à la main, avec deploy/install.sh (ou, pour ce seul script :
#    cp /opt/oddo/deploy/update.sh /usr/local/sbin/update.sh) ;
#  - V4 : RETOUR AUTOMATIQUE. Après le redémarrage, l'appli doit répondre dans les 90 s ; sinon
#    on remet la version d'avant, on redémarre, et on note la version fautive pour ne pas la
#    réessayer toutes les 15 min (une NOUVELLE version poussée sur « production » est essayée).
#    Les migrations ne font qu'ajouter (colonnes, tables) : l'ancienne version tourne sur la base
#    mise à jour. L'appli affiche l'annulation à l'administrateur (fichier dans /var/lib/oddo).
set -euo pipefail
# (chemins réglables seulement pour le test automatique de ce script : tests/test_v4_update_rollback.py)
APP=${ODDO_APP:-/opt/oddo}
ETC=${ODDO_ETC:-/etc/oddo}
VAR=${ODDO_VAR:-/var/lib/oddo}
BACKUP=${ODDO_BACKUP:-/usr/local/sbin/backup.sh}
BRANCH=production
FORCE=$ETC/update-now
HOUR=$(TZ=Africa/Casablanca date +%-H)
if [ ! -f "$FORCE" ] && [ "$HOUR" -ge 7 ] && [ "$HOUR" -lt 20 ]; then exit 0; fi

# code en lecture seule pour l'appli (une fois pour toutes, sans effet ensuite)
if [ -z "${ODDO_APP:-}" ]; then
  if [ "$(stat -c %U "$APP")" != "root" ]; then chown -R root:root "$APP"; fi
  chmod 700 "$APP/.git"
fi

BAD=$ETC/version-refusee
REPORT=$VAR/mise_a_jour_annulee.json
PORT=$(sed -n "s/^ODDO_PORT=['\"]*\([0-9]*\).*/\1/p" "$ETC/env" 2>/dev/null | head -1 || true)
PORT=${PORT:-8765}

# L'appli répond-elle ? (200 = tout va bien, 503 = elle tourne mais signale un souci de base ou
# de moteur : ce n'est pas le code qui l'empêche de démarrer). Jusqu'à 90 s.
alive() {
  for _ in $(seq 1 "${ODDO_HEALTH_TRIES:-18}"); do
    sleep "${ODDO_HEALTH_STEP:-5}"
    code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 4 "http://127.0.0.1:$PORT/api/health" || true)
    if [ "$code" = "200" ] || [ "$code" = "503" ]; then return 0; fi
  done
  return 1
}

git -C "$APP" fetch -q --depth 20 origin "+refs/heads/$BRANCH:refs/remotes/origin/$BRANCH"
NEW=$(git -C "$APP" rev-parse "origin/$BRANCH")
PREV=$(git -C "$APP" rev-parse HEAD)
if [ "$PREV" = "$NEW" ]; then
  rm -f "$FORCE"; exit 0
fi
if [ -f "$BAD" ] && [ "$(cat "$BAD")" = "$NEW" ]; then
  echo "Version ${NEW:0:7} déjà refusée (l'appli ne démarrait pas) : on attend une version corrigée."
  rm -f "$FORCE"; exit 0
fi
echo "Mise à jour ${PREV:0:7} -> ${NEW:0:7}"
"$BACKUP" || { echo "Sauvegarde en échec : mise à jour annulée"; exit 1; }
git -C "$APP" reset -q --hard "$NEW"
"$APP/.venv/bin/pip" install -q -r "$APP/requirements.txt" || echo "Installation des paquets en échec"
rm -f "$FORCE"
systemctl restart oddo.service
if alive; then
  rm -f "$BAD"
  echo "Version ${NEW:0:7} en ligne."
  exit 0
fi

echo "L'appli ne répond pas après la mise à jour : retour à ${PREV:0:7}."
journalctl -u oddo.service -n 60 --no-pager > "$VAR/mise_a_jour_annulee.log" 2>&1 || true
echo "$NEW" > "$BAD"
git -C "$APP" reset -q --hard "$PREV"
"$APP/.venv/bin/pip" install -q -r "$APP/requirements.txt" || true
systemctl restart oddo.service
OK=false
if alive; then OK=true; fi
printf '{"at":"%s","refused":"%s","back_to":"%s","back_ok":%s}\n' \
  "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "${NEW:0:7}" "${PREV:0:7}" "$OK" > "$REPORT"
chmod 644 "$REPORT" "$VAR/mise_a_jour_annulee.log" 2>/dev/null || true
if [ "$OK" = true ]; then echo "Retour à ${PREV:0:7} réussi."; else echo "ATTENTION : même la version précédente ne répond pas."; exit 1; fi
