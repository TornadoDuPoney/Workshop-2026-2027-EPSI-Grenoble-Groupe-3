# Runbook — Service de paiement indisponible

## Symptômes

- Les paiements échouent côté frontend (« Service de paiement indisponible »).
- api-paiement renvoie des 503, ou ne répond plus (conteneur arrêté).
- Le dashboard affiche api-paiement en « down ».

## Diagnostic

1. État du conteneur : `docker compose ps api-paiement`.
2. Logs : `docker compose logs --tail=50 api-paiement`.
3. Sonde de vie : `curl http://localhost:8000/health`.

## Remédiation

- Conteneur arrêté ou en erreur → `docker compose up -d api-paiement`.
- Conteneur sain mais saturé → identifier et bloquer la source (runbook DDoS),
  puis redémarrer.
- Après remédiation, prouver la reprise par une transaction de contrôle :
  `curl -X POST "http://localhost:8080/pay?amount=5"`.

## RTO / RPO

Objectif de reprise (RTO) : moins de 60 secondes. Aucune transaction validée
ne doit être perdue (RPO 0) — les transactions en échec ne débitent pas le
compte, elles sont simplement rejetées.

## Escalade

Si la reprise automatique échoue plusieurs fois d'affilée, c'est le signe d'un
problème plus profond (attaque distribuée, défaillance de l'hôte). Repartir
d'un état propre : `docker compose down && docker compose up -d`.
