# SIEM Wazuh — PROJECT RESILIENCE-ALPHA

Wazuh est le **SIEM/XDR** central du projet. Il remplace Loki/Promtail et
apporte la brique *sécurité* que l'observabilité (Prometheus/Grafana) ne
couvrait pas :

- **centralisation des logs** de l'hôte et des conteneurs ;
- **HIDS / FIM** : surveillance d'intégrité des fichiers (`/etc`, `/usr/bin`…) ;
- **détection de vulnérabilités** et **SCA** (conformité/benchmarks) ;
- **inventaire système** (syscollector) ;
- **alertes mappées MITRE ATT&CK** sur les incidents de la plateforme de
  paiement (détection ML → remédiation autonome), avec l'IP de l'attaquant.

Base : image officielle Wazuh `4.9.2`, déploiement *single-node*.

## Démarrage

```bash
cd infra/wazuh
chmod +x start-wazuh.sh
./start-wazuh.sh
```

Le script règle `vm.max_map_count`, crée le dossier de logs partagé
`/var/log/resilience`, génère les certificats TLS une fois, lance la stack, puis
**injecte les règles custom** (`local_rules.xml`) dans le manager et les recharge.

> Les règles ne sont volontairement **pas** montées en volume : un fichier monté
> dans `/var/ossec/etc` empêcherait Docker de peupler ce volume depuis l'image
> (le manager ne démarrerait pas). Elles sont donc copiées après le démarrage ;
> elles persistent ensuite dans le volume `wazuh_etc`.

> L'indexer (OpenSearch) met **1 à 2 minutes** à être prêt au premier démarrage.

Interface : **https://localhost:8443** — `admin` / `SecretPassword`
(certificat auto-signé : accepter l'avertissement du navigateur).

## Comment la plateforme alimente le SIEM

Le service **remediator** écrit un événement JSON dans
`/var/log/resilience/security.log` à chaque étape d'un incident :

| Événement            | Règle Wazuh | Niveau | MITRE |
|----------------------|-------------|--------|-------|
| `attack_detected`    | 100011      | 10     | T1498 |
| `attacker_blocked`   | 100012      | 12     | T1498 |
| `incident_remediated`| 100013/14   | 12     | T1498 |

Wazuh lit ce fichier (`localfile`, format JSON), décode les champs et lève les
alertes définies dans `config/wazuh_cluster/local_rules.xml`. Les logs bruts de
tous les conteneurs sont également ingérés pour l'agrégation.

## Voir les alertes

Dans le dashboard Wazuh : **Threat Hunting** / **Security events**, filtrer sur
`rule.groups: resilience_alpha` ou `rule.id: 100013`. On y retrouve l'IP de
l'attaquant, le type d'attaque et la preuve de reprise.

## Démo de bout en bout

```bash
# 1. plateforme up (autre terminal, depuis infra/compose)
cd ../compose && docker compose up -d --build && cd ../wazuh

# 2. Wazuh up
./start-wazuh.sh

# 3. déclencher une attaque depuis la console de démo
#    http://localhost:8070  ->  « Lancer l'attaque »
#    => le detector détecte, le remediator corrige ET émet les événements,
#       Wazuh lève les alertes MITRE dans https://localhost:8443
```

## Arrêt

```bash
docker compose down            # garde les données (volumes)
docker compose down -v         # efface tout (indexer, alertes…)
```

## Notes pour le rendu / la soutenance

- **Mot de passe** : `SecretPassword` est le défaut de l'image officielle —
  à changer avant le rendu (procédure Wazuh : outil `wazuh-passwords-tool`).
- **Ressources** : l'indexer est réglé à 1 Go de heap (`OPENSEARCH_JAVA_OPTS`
  dans `docker-compose.yml`). Confortable sur 32 Go de RAM.
- **Agrégation complète des logs** : par défaut Wazuh indexe les *alertes*. Pour
  rendre *tous* les logs conteneurs cherchables comme avec Loki, activer les
  archives (`<logall_json>yes</logall_json>` dans le manager + index `wazuh-archives`).
  Non nécessaire pour la démo (les alertes sécurité suffisent à la démonstration).
