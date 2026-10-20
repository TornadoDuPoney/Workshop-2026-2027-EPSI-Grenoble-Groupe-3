# Analyse d'incident par LLM local (Ollama)

À chaque incident, le moteur de remédiation fait rédiger une courte analyse
par un **modèle de langage installé localement** (Ollama), affichée sur le
dashboard. Aucun appel externe : le modèle tourne sur la machine.

## Mise en place (une fois)

Le conteneur `ollama` est déclaré dans le docker-compose. Après le premier
`docker compose up`, télécharger le modèle (une seule fois, ~2 Go) :

```bash
docker exec resilience-ollama ollama pull llama3.2:3b
```

Le modèle persiste ensuite dans le volume `ollama-models` ; il n'est pas
retéléchargé aux redémarrages.

## Vérifier

```bash
docker exec resilience-ollama ollama list          # le modèle apparaît
```

Après une attaque, l'analyse s'affiche sous l'incident dans la timeline du
dashboard (« Analyse IA · LLM local »). Si le modèle n'est pas encore
téléchargé ou que le LLM est lent, la remédiation fonctionne quand même :
l'analyse reste simplement vide (dégradation gracieuse).

## Choix du modèle

`llama3.2:3b` est léger (~2 Go), tourne sur CPU et répond correctement en
français. Pour une machine plus puissante, `qwen2.5:7b` ou `mistral` donnent
de meilleures analyses au prix d'un temps de réponse plus long. Changer le
modèle : variable `OLLAMA_MODEL` du service `remediator` dans le compose
(penser à faire `ollama pull` du nouveau modèle).
