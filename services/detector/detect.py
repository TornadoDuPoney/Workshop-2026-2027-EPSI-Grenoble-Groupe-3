"""
Détecteur d'anomalies — RESILIENCE-ALPHA.

Boucle en continu :
  1. interroge Prometheus (débit, latence p95, taux d'erreur) ;
  2. applique le modèle Isolation Forest entraîné sur du trafic sain ;
  3. si anomalie -> POST au moteur de remédiation.

Si le modèle n'est pas trouvé, bascule sur un repli par seuils simples :
la démo reste fonctionnelle même sans entraînement préalable.
"""
import os
import time

import numpy as np
import requests

MODEL_PATH = os.getenv("MODEL_PATH", "/app/detector_model.joblib")
PROM_URL = os.getenv("PROM_URL", "http://prometheus:9090")
REMEDIATOR_URL = os.getenv("REMEDIATOR_URL", "http://remediator:8000/alert")
POLL_SECONDS = int(os.getenv("POLL_SECONDS", "5"))
COOLDOWN_SECONDS = int(os.getenv("COOLDOWN_SECONDS", "45"))

# Seuils de sécurité (garde-fou de la détection hybride)
LAT_P95_MAX = float(os.getenv("LAT_P95_MAX", "0.3"))      # secondes
ERR_RATE_MAX = float(os.getenv("ERR_RATE_MAX", "0.5"))    # erreurs/s

# En dessous de ce débit, le service est au repos : aucun paiement à protéger,
# donc aucun incident possible. Évite les faux positifs quand rien ne circule.
MIN_ACTIVE_RPS = float(os.getenv("MIN_ACTIVE_RPS", "1.0"))

# Fenêtre d'observation des métriques. Plus courte = détection plus réactive
# (attaques brèves, RTO réduit) ; plus longue = plus lissée. 15s est un bon
# compromis réactivité / absence de faux positifs (validé par la campagne).
WINDOW = os.getenv("METRICS_WINDOW", "15s")

# Requêtes PromQL
Q_RPS = f'sum(rate(payments_total[{WINDOW}]))'
Q_LAT = f'histogram_quantile(0.95, sum(rate(payment_latency_seconds_bucket[{WINDOW}])) by (le))'
Q_ERR = f'sum(rate(payments_total{{status="error"}}[{WINDOW}]))'


def prom_query(expr: str) -> float:
    """Exécute une requête instantanée Prometheus et renvoie une valeur float."""
    try:
        r = requests.get(
            f"{PROM_URL}/api/v1/query", params={"query": expr}, timeout=4
        )
        result = r.json()["data"]["result"]
        if not result:
            return 0.0
        value = float(result[0]["value"][1])
        return 0.0 if np.isnan(value) else value
    except Exception as exc:  # Prometheus pas prêt, réseau, etc.
        print(f"[detector] requête échouée ({expr[:30]}...): {exc}", flush=True)
        return 0.0


def load_model():
    """Charge le modèle si présent, sinon None (repli seuils)."""
    try:
        import joblib
        model = joblib.load(MODEL_PATH)
        print(f"[detector] modèle chargé depuis {MODEL_PATH}", flush=True)
        return model
    except Exception as exc:
        print(f"[detector] pas de modèle ({exc}) -> repli par seuils", flush=True)
        return None


def is_anomaly(model, rps: float, lat: float, err: float) -> str:
    """
    Détection HYBRIDE : renvoie la raison du déclenchement, ou "" si tout va bien.

    Deux détecteurs complémentaires :
      - le modèle ML (Isolation Forest) repère les formes d'anomalie apprises ;
      - un garde-fou par seuils de sécurité attrape toute dérive franche,
        même si le ML la manque (robustesse de la démo et de la production).
    Le système réagit dès que l'un OU l'autre lève une alerte.
    """
    # 0. Service au repos : aucun trafic = aucun incident à détecter.
    if rps < MIN_ACTIVE_RPS and err <= ERR_RATE_MAX:
        return ""

    # 1. Détection ML (prioritaire) : le modèle Isolation Forest reconnaît la
    #    forme anormale (latence et erreurs élevées) apprise sur du trafic sain.
    if model is not None:
        import pandas as pd
        x = pd.DataFrame([[rps, lat, err]], columns=["rps", "latency_p95", "error_rate"])
        if int(model.predict(x)[0]) == -1:
            return "forme anormale détectée par le modèle ML (Isolation Forest)"

    # 2. Garde-fou par seuils : filet de sécurité si le ML manque une dérive.
    if lat > LAT_P95_MAX:
        return f"latence {lat:.3f}s > {LAT_P95_MAX}s (seuil de sécurité)"
    if err > ERR_RATE_MAX:
        return f"taux d'erreur {err:.1f}/s > {ERR_RATE_MAX}/s (seuil de sécurité)"

    return ""


def alert_remediator(rps: float, lat: float, err: float) -> None:
    """Notifie le moteur de remédiation."""
    try:
        resp = requests.post(
            REMEDIATOR_URL,
            json={"rps": rps, "latency_p95": lat, "error_rate": err},
            timeout=30,
        )
        print(f"[detector] remédiation déclenchée -> {resp.json()}", flush=True)
    except Exception as exc:
        print(f"[detector] échec notification remediator: {exc}", flush=True)


def main():
    print("[detector] démarrage de la boucle de surveillance", flush=True)
    model = load_model()
    while True:
        rps = prom_query(Q_RPS)
        lat = prom_query(Q_LAT)
        err = prom_query(Q_ERR)
        print(
            f"[detector] rps={rps:.2f} lat_p95={lat:.3f}s err={err:.2f}/s",
            flush=True,
        )
        reason = is_anomaly(model, rps, lat, err)
        if reason:
            print(f"[detector] !!! ANOMALIE détectée — {reason}", flush=True)
            alert_remediator(rps, lat, err)
            time.sleep(COOLDOWN_SECONDS)  # anti-rebond pendant la reprise
        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    main()
