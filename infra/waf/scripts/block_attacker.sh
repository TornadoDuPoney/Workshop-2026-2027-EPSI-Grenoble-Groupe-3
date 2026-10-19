#!/bin/sh
# Blocage de l'attaquant au niveau du WAF — appelé par le remediator.
# Version de démarrage : marque le blocage et recharge nginx.
# À durcir : extraire l'IP source la plus bruyante des logs et l'ajouter
# à une deny-list nginx avant le reload.

echo "$(date -u +%FT%TZ) BLOCK attacker triggered" >> /var/log/waf-blocks.log

# Exemple de règle dynamique (à adapter à votre conf nginx/modsecurity) :
# echo "deny 192.168.137.50;" > /etc/nginx/conf.d/blocklist.conf
# nginx -s reload 2>/dev/null || true

exit 0
