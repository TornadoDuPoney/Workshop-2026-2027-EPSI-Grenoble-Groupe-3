# Campagne de tests de résilience — RESILIENCE-ALPHA

Chaque scénario est rejoué contre la plateforme ; le système doit détecter et se rétablir sur les attaques, et NE PAS réagir sur une charge légitime (cas de contrôle).

| Scénario | Profil | Attendu | Détecté | Reprise | RTO (s) | Verdict |
| --- | --- | --- | --- | --- | --- | --- |
| Flood volumétrique (DDoS) | 120 workers, 18 s | incident | oui | oui | 32.2 | OK |
| Burst intense (court) | 160 workers, 15 s | incident | oui | oui | 36.3 | OK |
| Montée progressive puis maintien | ramp 8 s -> 140 workers, maintien 16 s | incident | oui | oui | 28.2 | OK |
| Pression modérée soutenue | 85 workers, 16 s | incident | oui | oui | 34.2 | OK |
| Charge légitime élevée (contrôle) | 15 workers espacés, 14 s | aucun | non | oui | — | OK |
| Sonde discrète (contrôle) | 3 workers espacés, 10 s | aucun | non | oui | — | OK |

**Résultat global : 6/6 scénarios conformes.**
