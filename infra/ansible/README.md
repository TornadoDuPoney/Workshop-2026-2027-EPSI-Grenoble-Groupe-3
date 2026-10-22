# Configuration de l'observabilité par Ansible — RESILIENCE-ALPHA

Ce playbook génère de façon **reproductible** la configuration de Prometheus
et Grafana. Objectif : un déploiement documenté et rejouable, pas de réglage
manuel dans l'interface Grafana.

La centralisation des logs et le SIEM sont assurés par **Wazuh** (voir
`infra/wazuh/`), déployé par son propre script.

## Ce que fait le playbook

- **Prometheus** : génère `infra/prometheus/prometheus.yml` (scrape de l'API).
- **Grafana** : provisionne automatiquement la source de données Prometheus
  et un dashboard « RESILIENCE-ALPHA — Paiement » (débit, latence p95, erreurs).

## Prérequis

```bash
# installer Ansible (dans le venv du projet)
pip install ansible-core
```

## Utilisation

```bash
cd infra/ansible

# générer toutes les configurations
ansible-playbook -i inventory.ini site.yml

# configurations + déploiement docker compose
ansible-playbook -i inventory.ini site.yml -e deploy=true

# seulement une brique
ansible-playbook -i inventory.ini site.yml --tags grafana
```

## Après génération

Pour que Grafana charge ces fichiers, les montages correspondants doivent être
présents dans `docker-compose.yml` (voir le bloc d'intégration fourni). Une
fois en place :

```bash
cd ../compose
docker compose up -d
```

Grafana : http://localhost:3000 (admin / admin) — le dashboard et la source
de données apparaissent automatiquement, sans configuration manuelle.
