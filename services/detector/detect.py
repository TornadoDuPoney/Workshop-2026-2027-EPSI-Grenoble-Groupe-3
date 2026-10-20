"""
Détecteur d'anomalies — RESILIENCE-ALPHA.

Détection HYBRIDE : un modèle ML (Isolation Forest) pour les formes
d'anomalie apprises, DOUBLÉ d'un garde-fou par seuils de sécurité qui
attrape toute dérive franche même si le ML la manque. Le système réagit
dès que l'un OU l'autre lève une alerte — robuste en démo et en production.

Si le modèle est absent, seul le garde-fou par seuils fonctionne.
"""
import os
import time

import numpy as np
import requests

MODEL_PATH = os.getenv("MODEL_PATH", "/models/detector_model.joblib")
PROM_URL = os.getenv("PROM_URL", "http://prometheus:9090")
REMEDIATOR_URL = os.getenv("REMEDIATOR_URL", "http://remediator:8000/alert")
POLL_SECONDS = int(os.getenv("POLL_SECONDS", "5"))
COOLDOWN_SECONDS = int(os.getenv("COOLDOWN_SECONDS", "45"))

LAT_P95_MAX = float(os.getenv("LAT_P95_MAX", "0.3"))      # secondes
ERR_RATE_MAX = float(os.getenv("ERR_RATE_MAX", "0.5"))    # erreurs/s

Q_RPS = 'sum(rate(payments_total[30s]))'
Q_LAT = 'histogram_quantile(0.95, sum(rate(payment_latency_seconds_bucket[30s])) by (le))'
Q_ERR = 'sum(rate(payments_total{status="error"}[30s]))'


def prom_query(expr: str) -> float:
    try:
        r = requests.get(f"{PROM_URL}/api/v1/query", params={"query": expr}, timeout=4)
        result = r.json()["data"]["result"]
        if not result:
            return 0.0
        value = float(result[0]["value"][1])
        return 0.0 if np.isnan(value) else value
    except Exception as exc:
        print(f"[detector] requête échouée ({expr[:30]}...): {exc}", flush=True)
        return 0.0


def load_model():
    try:
        import joblib
        model = joblib.load(MODEL_PATH)
        print(f"[detector] modèle chargé depuis {MODEL_PATH}", flush=True)
        return model
    except Exception as exc:
        print(f"[detector] pas de modèle ({exc}) -> garde-fou par seuils seul", flush=True)
        return None


def is_anomaly(model, rps: float, lat: float, err: float) -> str:
    """Détection hybride : renvoie la raison du déclenchement, ou '' si sain."""
    if lat > LAT_P95_MAX:
        return f"latence {lat:.3f}s > {LAT_P95_MAX}s (seuil de sécurité)"
    if err > ERR_RATE_MAX:
        return f"taux d'erreur {err:.1f}/s > {ERR_RATE_MAX}/s (seuil de sécurité)"
    if model is not None:
        import pandas as pd
        x = pd.DataFrame([[rps, lat, err]], columns=["rps", "latency_p95", "error_rate"])
        if int(model.predict(x)[0]) == -1:
            return "forme anormale détectée par le modèle ML (Isolation Forest)"
    return ""


def alert_remediator(rps: float, lat: float, err: float) -> None:
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
        print(f"[detector] rps={rps:.2f} lat_p95={lat:.3f}s err={err:.2f}/s", flush=True)
        reason = is_anomaly(model, rps, lat, err)
        if reason:
            print(f"[detector] !!! ANOMALIE détectée — {reason}", flush=True)
            alert_remediator(rps, lat, err)
            time.sleep(COOLDOWN_SECONDS)
        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    main()
