# Runbook — Latence élevée (sans erreurs)

## Symptômes

- Latence p95 au-dessus de 0,3 s mais taux d'erreur proche de zéro.
- Débit normal ou légèrement élevé.
- Le service répond encore, mais lentement.

## Causes possibles

- Montée en charge légitime (afflux de clients) proche du seuil de saturation.
- Ralentissement d'une dépendance (base de données, service d'authentification).
- Contention de ressources sur l'hôte (CPU, mémoire).

## Diagnostic

1. Vérifier le débit : s'agit-il d'un pic légitime ou d'un flood ?
   Un pic légitime garde un taux d'erreur nul et des IP sources variées.
2. Consulter les logs centralisés (SIEM Wazuh) pour repérer une IP dominante
   (signe d'attaque) ou un message d'erreur de dépendance.
3. Vérifier l'état des conteneurs (`docker compose ps`).

## Remédiation

- Si pic légitime : pas de blocage. Envisager d'augmenter
  SATURATION_THRESHOLD ou de mettre l'API à l'échelle.
- Si une IP domine : traiter comme un DDoS (voir runbook DDoS).
- Si une dépendance est lente : redémarrer le conteneur concerné.

## À ne pas faire

Ne pas bloquer d'IP ni redémarrer agressivement sur une simple montée de
charge légitime : le modèle de détection est entraîné pour ne PAS alerter sur
un fort trafic tant que la latence reste basse et les erreurs nulles.
