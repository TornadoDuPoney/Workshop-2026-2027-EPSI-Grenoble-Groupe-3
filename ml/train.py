"""
Entraînement du détecteur d'anomalies (Isolation Forest) — RESILIENCE-ALPHA.

Étape 1 (mardi) : récolter du trafic sain puis entraîner le modèle.

Deux usages :
  python train.py --collect        # récolte N points depuis Prometheus -> metrics_normal.csv
  python train.py --train          # entraîne depuis le CSV -> detector_model.joblib

En l'absence de CSV réel, --synthetic génère un jeu sain plausible pour
amorcer la démo. Remplacez-le par vos vraies métriques dès que possible.
"""
import argparse
import time

import numpy as np
import pandas as pd
import requests
from sklearn.ensemble import IsolationForest
import joblib

import os
PROM_URL = os.getenv("PROM_URL", "http://localhost:9090")
CSV = "metrics_normal.csv"
MODEL = "detector_model.joblib"
COLS = ["rps", "latency_p95", "error_rate"]

Q = {
    "rps": 'sum(rate(payments_total[30s]))',
    "latency_p95": 'histogram_quantile(0.95, sum(rate(payment_latency_seconds_bucket[30s])) by (le))',
    "error_rate": 'sum(rate(payments_total{status="error"}[30s]))',
}


def query(expr):
    r = requests.get(f"{PROM_URL}/api/v1/query", params={"query": expr}, timeout=4)
    res = r.json()["data"]["result"]
    if not res:
        return 0.0
    v = float(res[0]["value"][1])
    return 0.0 if np.isnan(v) else v


def collect(points=180, interval=5):
    """Récolte des observations en charge NORMALE (lancez un trafic régulier)."""
    print(f"Récolte de {points} points toutes les {interval}s...")
    rows = []
    for i in range(points):
        rows.append({c: query(Q[c]) for c in COLS})
        if i % 10 == 0:
            print(f"  {i}/{points}")
        time.sleep(interval)
    pd.DataFrame(rows).to_csv(CSV, index=False)
    print(f"-> {CSV} écrit ({len(rows)} lignes)")


def synthetic(n=500):
    """Jeu sain synthétique pour amorcer la démo si pas encore de vraies données."""
    rng = np.random.default_rng(42)
    df = pd.DataFrame({
        "rps": rng.normal(12, 2.5, n).clip(0),
        "latency_p95": rng.normal(0.06, 0.015, n).clip(0.01),
        "error_rate": rng.normal(0.0, 0.02, n).clip(0),
    })
    df.to_csv(CSV, index=False)
    print(f"-> {CSV} synthétique écrit ({n} lignes)")


def train():
    df = pd.read_csv(CSV)
    model = IsolationForest(
        n_estimators=150, contamination=0.02, random_state=42
    )
    model.fit(df[COLS])
    joblib.dump(model, MODEL)
    print(f"-> {MODEL} entraîné sur {len(df)} points")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--collect", action="store_true", help="récolte depuis Prometheus")
    p.add_argument("--synthetic", action="store_true", help="jeu sain synthétique")
    p.add_argument("--train", action="store_true", help="entraîne le modèle")
    p.add_argument("--points", type=int, default=180)
    args = p.parse_args()

    if args.collect:
        collect(points=args.points)
    if args.synthetic:
        synthetic()
    if args.train:
        train()
    if not any([args.collect, args.synthetic, args.train]):
        print("Usage: --collect | --synthetic | --train (voir --help)")
