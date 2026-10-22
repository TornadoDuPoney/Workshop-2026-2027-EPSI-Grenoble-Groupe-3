/*
 * PROJECT RESILIENCE-ALPHA — objet connecté (ESP32).
 *
 * Voyant de sécurité physique du back-office : deux LED (verte / rouge)
 * pilotées par le PC Hôte via WiFi. Le back-office envoie, à chaque étape de
 * l'authentification, une requête HTTP :
 *
 *     POST http://<IP_ESP32>/led    body: {"state":"green_blink"}
 *
 * États (conformes à la consigne) :
 *   green_blink  -> visage reconnu           : vert CLIGNOTE (attente mot de passe)
 *   green_solid  -> accès accordé            : vert FIXE 30 s puis extinction
 *   red_blink    -> mauvais mot de passe     : rouge CLIGNOTE 10 fois
 *   red_solid    -> visage non reconnu       : rouge FIXE 30 s
 *   off          -> extinction immédiate
 *
 * Machine à états NON bloquante (millis) : le serveur HTTP reste réactif.
 */
#include <WiFi.h>
#include <WebServer.h>

// ============================ À PERSONNALISER ============================
const char* WIFI_SSID = "TON_RESEAU_WIFI";      // <-- nom du WiFi (même réseau que le PC Hôte)
const char* WIFI_PASS = "TON_MOT_DE_PASSE";     // <-- mot de passe du WiFi

const int PIN_GREEN = 33;   // GPIO de la LED VERTE  (change si câblée ailleurs)
const int PIN_RED   = 14;   // GPIO de la LED ROUGE  (change si câblée ailleurs)
// ========================================================================

const unsigned long SOLID_MS   = 30000;  // durée des états "fixe" : 30 s
const unsigned long BLINK_MS   = 300;    // demi-période de clignotement
const int           RED_BLINKS = 10;     // nombre de clignotements rouges

WebServer server(80);

enum LedState { IDLE, GREEN_BLINK, GREEN_SOLID, RED_BLINK, RED_SOLID };
LedState      state      = IDLE;
unsigned long stateStart = 0;
unsigned long lastToggle = 0;
bool          blinkOn    = false;
int           blinkCount = 0;

void allOff() {
  digitalWrite(PIN_GREEN, LOW);
  digitalWrite(PIN_RED, LOW);
}

void setState(LedState s) {
  state      = s;
  stateStart = millis();
  lastToggle = millis();
  blinkOn    = false;
  blinkCount = 0;
  allOff();
  Serial.print("[LED] etat -> ");
  Serial.println((int)s);
}

// POST /led  { "state": "..." }
void handleLed() {
  String body = server.hasArg("plain") ? server.arg("plain") : "";
  LedState s = IDLE;
  if      (body.indexOf("green_blink") >= 0) s = GREEN_BLINK;
  else if (body.indexOf("green_solid") >= 0) s = GREEN_SOLID;
  else if (body.indexOf("red_blink")   >= 0) s = RED_BLINK;
  else if (body.indexOf("red_solid")   >= 0) s = RED_SOLID;
  else                                       s = IDLE;   // "off" ou inconnu
  setState(s);
  server.send(200, "application/json", "{\"ok\":true}");
}

void setup() {
  Serial.begin(115200);
  pinMode(PIN_GREEN, OUTPUT);
  pinMode(PIN_RED, OUTPUT);
  allOff();

  // Petit test au démarrage : vert puis rouge, pour vérifier le câblage.
  digitalWrite(PIN_GREEN, HIGH); delay(300); digitalWrite(PIN_GREEN, LOW);
  digitalWrite(PIN_RED, HIGH);   delay(300); digitalWrite(PIN_RED, LOW);

  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASS);
  Serial.print("Connexion WiFi");
  while (WiFi.status() != WL_CONNECTED) { delay(500); Serial.print("."); }
  Serial.println();
  Serial.print(">>> Objet connecte. LED_URL a mettre dans le back-office : http://");
  Serial.println(WiFi.localIP());

  server.on("/led", HTTP_POST, handleLed);
  server.on("/", HTTP_GET, []() { server.send(200, "text/plain", "RESILIENCE-ALPHA LED OK"); });
  server.begin();
}

void loop() {
  server.handleClient();
  unsigned long now = millis();

  switch (state) {
    case GREEN_BLINK:  // clignote tant qu'un nouvel état n'arrive pas
      if (now - lastToggle >= BLINK_MS) {
        lastToggle = now; blinkOn = !blinkOn;
        digitalWrite(PIN_GREEN, blinkOn ? HIGH : LOW);
      }
      break;

    case GREEN_SOLID:
      digitalWrite(PIN_GREEN, HIGH);
      if (now - stateStart >= SOLID_MS) setState(IDLE);
      break;

    case RED_SOLID:
      digitalWrite(PIN_RED, HIGH);
      if (now - stateStart >= SOLID_MS) setState(IDLE);
      break;

    case RED_BLINK:    // clignote RED_BLINKS fois puis s'éteint
      if (now - lastToggle >= BLINK_MS) {
        lastToggle = now; blinkOn = !blinkOn;
        digitalWrite(PIN_RED, blinkOn ? HIGH : LOW);
        if (!blinkOn) {                 // fin d'un cycle complet
          blinkCount++;
          if (blinkCount >= RED_BLINKS) setState(IDLE);
        }
      }
      break;

    case IDLE:
    default:
      allOff();
      break;
  }
}
