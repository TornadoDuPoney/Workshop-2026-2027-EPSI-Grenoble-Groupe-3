# Objet connecté ESP32 — voyant de sécurité RESILIENCE-ALPHA

Deux LED (verte / rouge) pilotées par WiFi depuis le back-office. Elles
matérialisent physiquement l'état de l'authentification par reconnaissance
faciale.

| État reçu (`/led`) | Déclencheur back-office | Voyant |
|---|---|---|
| `green_blink` | visage reconnu | 🟢 clignote (attente du mot de passe) |
| `green_solid` | accès accordé | 🟢 fixe 30 s puis s'éteint |
| `red_blink`   | mauvais mot de passe | 🔴 clignote 10 fois |
| `red_solid`   | visage non reconnu | 🔴 fixe 30 s |

## 1. Câblage

Carte **ESP32** (module ESP-WROOM-32). Chaque LED via une résistance ~220–330 Ω :

```
GPIO 26 ──[ R 220Ω ]──▶|── GND     (LED VERTE : patte longue = +, côté GPIO)
GPIO 25 ──[ R 220Ω ]──▶|── GND     (LED ROUGE)
```

- Patte **longue** (anode, +) côté résistance/GPIO ; patte **courte** (cathode, −) vers **GND**.
- Relier un **GND** de l'ESP32 au rail « − » de la breadboard.
- Si tu as câblé sur d'autres broches, change simplement `PIN_GREEN` / `PIN_RED`
  en haut de `src/main.cpp`.

> Broches sûres en sortie sur ESP32 : 25, 26, 27, 32, 33. Évite 0, 2, 12, 15
> (démarrage) et 34–39 (entrée seule).

## 2. Configurer et téléverser

Dans `src/main.cpp`, renseigne ton WiFi (le **même réseau** que le PC Hôte) :

```cpp
const char* WIFI_SSID = "TON_RESEAU_WIFI";
const char* WIFI_PASS = "TON_MOT_DE_PASSE";
```

Puis, dans le dossier `iot/esp32-led/` :

```bash
pio run -t upload       # compile et téléverse
pio device monitor      # affiche l'adresse IP de l'objet
```

Au démarrage, la verte puis la rouge clignotent une fois (test de câblage), et le
moniteur série affiche :

```
>>> Objet connecte. LED_URL a mettre dans le back-office : http://192.168.x.x
```

> Dans CLion : ouvrir ce dossier, laisser le plugin PlatformIO détecter le projet,
> puis utiliser les actions **PlatformIO Upload** et **Monitor**.

## 3. Brancher le back-office sur l'objet

Reporte l'IP affichée dans le `docker-compose.yml` de la plateforme, service
`backoffice` :

```yaml
    environment:
      FACE_URL: "http://face-reco:8000"
      LED_URL: "http://192.168.x.x"      # <-- IP de l'ESP32
```

Puis recrée le conteneur back-office :

```bash
cd infra/compose
docker compose up -d backoffice
```

> Le PC Hôte et l'ESP32 doivent être sur le **même réseau**. Le conteneur
> back-office sort vers le LAN via l'hôte : il atteint l'IP de l'ESP32 sans
> configuration supplémentaire.

## 4. Tester sans le back-office (optionnel)

Depuis le PC Hôte, on peut piloter l'objet directement :

```bash
curl -X POST http://192.168.x.x/led -H "Content-Type: application/json" -d '{"state":"green_blink"}'
curl -X POST http://192.168.x.x/led -H "Content-Type: application/json" -d '{"state":"red_blink"}'
curl -X POST http://192.168.x.x/led -H "Content-Type: application/json" -d '{"state":"off"}'
```

## 5. Démo de bout en bout

1. Back-office : `http://localhost:8090`.
2. Saisir un identifiant enrôlé et se présenter à la caméra → visage reconnu →
   🟢 **clignote**.
3. Bon mot de passe → 🟢 **fixe 30 s** (accès). Mauvais → 🔴 **10 clignotements**.
4. Identifiant enrôlé mais autre visage → non reconnu → 🔴 **fixe 30 s**.
