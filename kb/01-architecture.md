# Architecture RESILIENCE-ALPHA

La plateforme est un système de paiement fictif conteneurisé, orchestré par
Docker Compose, avec une chaîne de cyber-résilience autonome.

## Services

- **api-paiement** : API métier (FastAPI) qui traite les transactions. Expose
  /health, /pay, /metrics. Se dégrade sous forte charge concurrente (latence
  élevée puis erreurs 503). Tient une liste noire d'IP (blocage applicatif).
- **frontend** : site de paiement (React/Tailwind) qui appelle api-paiement.
- **detector** : détection d'anomalie. Lit les métriques Prometheus, applique
  un modèle Isolation Forest (ML) doublé d'un garde-fou par seuils. Déclenche
  la remédiation sans intervention humaine.
- **remediator** : moteur de remédiation. Identifie l'attaquant dans les logs,
  le bloque (WAF + API), redémarre le service, prouve la reprise par une
  transaction de contrôle. Rédige une analyse via le LLM local.
- **waf** : pare-feu applicatif (ModSecurity/Nginx), point d'entrée exposé.
- **prometheus / grafana** : observabilité (métriques temps réel, dashboards).
- **wazuh** : SIEM/XDR (manager + indexer + dashboard). Centralise les logs,
  surveille l'intégrité des fichiers (FIM), détecte les vulnérabilités, et
  lève des alertes mappées MITRE ATT&CK sur les incidents de la plateforme.
- **ollama** : LLM local (llama3.2:3b) pour l'analyse d'incident et l'assistant.
- **qdrant** : base vectorielle pour la recherche documentaire (RAG).
- **dashboard** : supervision temps réel (état, courbes, timeline de reprise).
- **console** : pilotage de la démo (trafic, attaque, transaction de test).

## Réseaux

Trois réseaux segmentés : `front` (exposé via WAF), `back` (métier), `obs`
(observabilité). Seul le port 8080 (WAF) est destiné au réseau du groupe.

## Boucle de résilience

Métriques → détection ML → remédiation autonome → transaction de contrôle.
Le temps entre le début de l'incident et la transaction de contrôle réussie
est l'indicateur de reprise (objectif RTO < 60 s, RPO 0).

## Ports exposés

api-paiement 8000, waf 8080, grafana 3000, prometheus 9090, dashboard 8050,
frontend 8060, console 8070, qdrant 6333.
