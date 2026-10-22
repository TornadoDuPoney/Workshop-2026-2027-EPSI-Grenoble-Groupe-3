#!/usr/bin/env bash
# =====================================================================
#  Démarrage du SIEM Wazuh — PROJECT RESILIENCE-ALPHA
#  À lancer sur le PC Hôte, depuis le dossier infra/wazuh/.
#
#  Fait, dans l'ordre :
#    1. règle le prérequis système de l'indexer (vm.max_map_count) ;
#    2. crée le dossier de logs partagé avec la plateforme ;
#    3. génère les certificats TLS (une seule fois) ;
#    4. lance la stack Wazuh (manager + indexer + dashboard).
# =====================================================================
set -euo pipefail
cd "$(dirname "$0")"

echo "==> 1/4  Prérequis système : vm.max_map_count=262144"
if [ "$(sysctl -n vm.max_map_count 2>/dev/null || echo 0)" -lt 262144 ]; then
  sudo sysctl -w vm.max_map_count=262144
  # Rendre le réglage persistant au redémarrage.
  if ! grep -q "vm.max_map_count" /etc/sysctl.conf 2>/dev/null; then
    echo "vm.max_map_count=262144" | sudo tee -a /etc/sysctl.conf >/dev/null
  fi
else
  echo "    déjà OK."
fi

echo "==> 2/5  Dossier de logs partagé avec la plateforme : /var/log/resilience"
sudo mkdir -p /var/log/resilience
sudo chmod 777 /var/log/resilience   # écrit par le remediator, lu par Wazuh
# Le fichier doit EXISTER avant le démarrage du manager : logcollector n'ouvre
# que les fichiers présents au lancement (sinon il abandonne après quelques essais).
sudo touch /var/log/resilience/security.log
sudo chmod 666 /var/log/resilience/security.log

echo "==> 3/5  Génération des certificats TLS (une seule fois)"
if [ ! -f config/wazuh_indexer_ssl_certs/root-ca.pem ]; then
  docker compose -f generate-indexer-certs.yml run --rm generator
else
  echo "    certificats déjà présents, on saute."
fi

echo "==> 4/5  Lancement de la stack Wazuh"
docker compose up -d

echo "==> 5/5  Attente de l'initialisation du manager puis injection des règles"
# Le manager est prêt quand son fichier ar.conf (généré au démarrage) existe.
printf "    initialisation "
for _ in $(seq 1 60); do
  if docker compose exec -T wazuh.manager test -f /var/ossec/etc/shared/ar.conf 2>/dev/null; then
    ready=1; break
  fi
  printf "."; sleep 3
done
echo
if [ "${ready:-0}" = "1" ]; then
  # Les règles custom sont injectées DANS le volume (pas montées), puis chargées.
  docker compose cp config/wazuh_cluster/local_rules.xml \
    wazuh.manager:/var/ossec/etc/rules/local_rules.xml
  docker compose exec -T wazuh.manager chown wazuh:wazuh /var/ossec/etc/rules/local_rules.xml
  docker compose exec -T wazuh.manager /var/ossec/bin/wazuh-control restart >/dev/null
  echo "    règles RESILIENCE-ALPHA installées et chargées."
else
  echo "    ATTENTION : le manager n'a pas fini d'initialiser à temps."
  echo "    Vérifiez : docker compose logs --tail=40 wazuh.manager"
fi

cat <<'EOF'

=====================================================================
 Wazuh démarré.

 Interface :  https://localhost:8443
 Identifiant : admin
 Mot de passe : SecretPassword     (à changer pour le rendu !)

 Vérifier que tout tourne :
   docker compose exec wazuh.manager /var/ossec/bin/wazuh-control status
=====================================================================
EOF
