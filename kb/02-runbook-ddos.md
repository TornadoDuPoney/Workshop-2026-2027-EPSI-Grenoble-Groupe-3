# Runbook — Déni de service (DDoS applicatif)

## Symptômes

- Débit (req/s) anormalement élevé sur api-paiement.
- Latence p95 qui dépasse 0,3 s et grimpe vers 0,48 s (plafond de saturation).
- Taux d'erreur 503 (« Service saturé ») qui augmente.
- Le modèle Isolation Forest classe l'observation comme anormale.

## Cause

Un flood HTTP sature l'API : trop de transactions concurrentes dépassent le
seuil de saturation (SATURATION_THRESHOLD), ce qui ralentit le service puis
provoque des rejets 503.

## Remédiation automatique (déjà en place)

1. **Identifier l'attaquant** : analyser les logs de l'API et du WAF, compter
   les requêtes par IP source, retenir l'IP dominante.
2. **Bloquer l'IP** à deux niveaux : règle `deny` au WAF et liste noire
   applicative de l'API (rejet 403). Le blocage est persistant (survit au
   redémarrage).
3. **Redémarrer** le conteneur api-paiement pour vider la saturation.
4. **Prouver la reprise** par une transaction de contrôle.

## Vérification

- Dashboard : le bandeau repasse au vert, la timeline affiche l'IP bloquée.
- `curl http://localhost:8000/admin/blocklist` doit contenir l'IP de l'attaquant.
- Le compteur `payments_blocked_total` augmente si l'attaquant cogne encore.

## Rejouer / réinitialiser

Pour une nouvelle démo, débloquer l'IP :
`curl -X POST http://localhost:8000/admin/unblock -d '{}'`

## Point de vigilance

Un flood distribué (plusieurs IP) peut dépasser le blocage mono-IP. La parade
production : rate-limiting au WAF et mise à l'échelle horizontale de l'API.
