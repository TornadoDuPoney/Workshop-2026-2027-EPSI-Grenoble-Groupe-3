# PROJECT RESILIENCE-ALPHA

Démonstrateur de cyber-résilience : un SI de paiement fictif qui encaisse une
attaque et se rétablit **sans intervention humaine**.

## Architecture

```
PC Attaquant ──(flood HTTP)──> [ WAF :8080 ] ──> [ api-paiement ] ──> [ db ]
                                                        │ /metrics
                                                        ▼
                                                 [ prometheus ] ──> [ grafana :3000 ]
                                                        │
                                                        ▼
                                                  [ detector ]  (Isolation Forest)
                                                        │ alerte
                                                        ▼
                                                 [ remediator ] ──> bloque + redémarre
                                                        │
                                                        ▼
                                           transaction de contrôle = PREUVE de reprise
```

Réseaux segmentés : `front` (exposé via WAF), `back` (métier), `obs` (observabilité).
Seul le port **8080** (WAF) est destiné au réseau du groupe.

## Démarrage rapide

```bash
# 1. Construire et lancer la plateforme (sur le PC Hôte)
cd infra/compose
docker compose up --build -d

# 2. (optionnel) Entraîner le modèle ML — sinon repli automatique par seuils
cd ../../ml
pip install -r ../services/detector/requirements.txt pandas
python train.py --synthetic --train      # amorçage ; remplacer par --collect dès que possible
cp detector_model.joblib .                # le detector le monte via le volume ../../ml

# 3. Générer du trafic normal (laisse tourner)
cd ../scripts
python trafic_normal.py --url http://localhost:8080/pay --rps 10
```

## Vérifier la boucle de résilience

```bash
# État avant : une transaction passe
curl -X POST "http://localhost:8080/pay?amount=5"

# Lancer l'attaque DEPUIS LE PC ATTAQUANT
python attack/ddos.py --target http://192.168.137.1:8080/pay

# Observer : le detector logge l'anomalie, le remediator agit
docker logs -f resilience-detector
docker logs -f resilience-remediator

# État après : l'historique montre recovered=true
curl http://localhost:8080/pay?amount=5      # repasse
# (si le remediator est exposé en interne) curl http://<host>/history
```

## SIEM — Wazuh

La centralisation des logs et la détection de sécurité sont assurées par
**Wazuh** (SIEM/XDR, `infra/wazuh/`), qui a remplacé Loki/Promtail. Il surveille
l'hôte (FIM, vulnérabilités, SCA) et reçoit les événements de sécurité de la
plateforme : à chaque incident, le remediator émet un événement JSON que Wazuh
transforme en **alerte mappée MITRE ATT&CK** (avec l'IP de l'attaquant).

```bash
cd infra/wazuh
chmod +x start-wazuh.sh
./start-wazuh.sh
# Interface : https://localhost:8443  (admin / SecretPassword)
```

Voir `infra/wazuh/README.md` pour le détail des règles et la démo de bout en bout.

## Points à défendre devant le jury

- **Preuve de reprise** : le remediator finit toujours par une *transaction de
  contrôle* ; un simple redémarrage de conteneur ne suffit pas.
- **Droits élevés du remediator** : accès au socket Docker, donc isolé sur le
  réseau `back`, aucun port exposé, aucune interface d'admin ouverte.
- **Détection ML** : Isolation Forest entraîné sur du trafic sain ; repli par
  seuils documenté pour la robustesse de la démo.
- **SIEM Wazuh** : on distingue *observabilité* (Prometheus/Grafana) et *SIEM de
  sécurité* (Wazuh : FIM, vulnérabilités, corrélation, MITRE ATT&CK). La boucle
  autonome laisse une trace de sécurité horodatée et attribuée dans le SIEM.

## Sécurité des rendus

Aucun secret en clair dans l'archive. Changez le mot de passe Grafana,
chiffrez `secrets/` avec SOPS avant le commit final.
