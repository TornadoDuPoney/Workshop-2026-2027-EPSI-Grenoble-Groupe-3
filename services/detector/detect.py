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

# Seuils du repli (utilisés seulement si le modèle est absent)
LAT_P95_MAX = float(os.getenv("LAT_P95_MAX", "0.3"))      # secondes
ERR_RATE_MAX = float(os.getenv("ERR_RATE_MAX", "0.5"))    # erreurs/s

# Requêtes PromQL
Q_RPS = 'sum(rate(payments_total[1m]))'
Q_LAT = 'histogram_quantile(0.95, sum(rate(payment_latency_seconds_bucket[1m])) by (le))'
Q_ERR = 'sum(rate(payments_total{status="error"}[1m]))'


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


def is_anomaly(model, rps: float, lat: float, err: float) -> bool:
    """Décide si l'observation est anormale (ML si dispo, sinon seuils)."""
    if model is not None:
        # Isolation Forest : -1 = anomalie, 1 = normal.
        # DataFrame avec les mêmes noms de colonnes qu'à l'entraînement
        # (évite le UserWarning scikit-learn et fiabilise la prédiction).
        import pandas as pd
        x = pd.DataFrame([[rps, lat, err]], columns=["rps", "latency_p95", "error_rate"])
        return int(model.predict(x)[0]) == -1
    # Repli : latence OU taux d'erreur au-dessus du seuil
    return lat > LAT_P95_MAX or err > ERR_RATE_MAX


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
        if is_anomaly(model, rps, lat, err):
            print("[detector] !!! ANOMALIE détectée", flush=True)
            alert_remediator(rps, lat, err)
            time.sleep(COOLDOWN_SECONDS)  # anti-rebond pendant la reprise
        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    main()
