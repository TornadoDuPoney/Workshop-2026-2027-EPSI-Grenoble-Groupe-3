#!/bin/sh
# Blocage de l'attaquant au niveau du WAF — appelé par le remediator.
# Usage : block_attacker.sh <ip>
# Écrit une règle nginx "deny <ip>;" dans une liste de blocage incluse par
# la configuration, puis recharge nginx. Best-effort : si le rechargement
# échoue dans cette image, le blocage applicatif (côté API) prend le relais.

IP="$1"
LOG=/var/log/waf-blocks.log
BLOCKLIST=/etc/nginx/conf.d/blocklist.conf

if [ -z "$IP" ]; then
    echo "$(date -u +%FT%TZ) block appelé sans IP" >> "$LOG" 2>/dev/null
    exit 0
fi

echo "$(date -u +%FT%TZ) BLOCK $IP" >> "$LOG" 2>/dev/null

# Ajoute la règle si elle n'existe pas déjà.
if ! grep -q "deny $IP;" "$BLOCKLIST" 2>/dev/null; then
    echo "deny $IP;" >> "$BLOCKLIST" 2>/dev/null
fi

# Recharge nginx pour appliquer (ignore l'erreur si la conf ne l'inclut pas).
nginx -s reload 2>/dev/null || true

exit 0
