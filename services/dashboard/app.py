"""
Backend du dashboard de supervision — RESILIENCE-ALPHA.

Agrège les sources internes et expose une API propre pour le front :
  GET /api/state    -> métriques live (rps, latence p95, taux d'erreur) + verdict
  GET /api/services -> état up/down de chaque brique (via Prometheus targets)
  GET /api/incidents-> historique des remédiations (depuis le remediator)
  GET /              -> sert la page du dashboard

Le front n'interroge jamais Prometheus en direct : tout passe par ce backend,
ce qui évite les problèmes de CORS et garde Prometheus interne.
"""
import os

import requests
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

app = FastAPI(title="Dashboard RESILIENCE-ALPHA")

PROM_URL = os.getenv("PROM_URL", "http://prometheus:9090")
REMEDIATOR_URL = os.getenv("REMEDIATOR_URL", "http://remediator:8000")

# Seuils d'affichage (alignés sur le detector) pour colorer le verdict.
LAT_WARN = float(os.getenv("LAT_WARN", "0.3"))
ERR_WARN = float(os.getenv("ERR_WARN", "0.5"))

Q_RPS = 'sum(rate(payments_total[30s]))'
Q_LAT = 'histogram_quantile(0.95, sum(rate(payment_latency_seconds_bucket[30s])) by (le))'
Q_ERR = 'sum(rate(payments_total{status="error"}[30s]))'
Q_SUCC = 'sum(payments_total{status="success"})'
Q_ERRTOT = 'sum(payments_total{status="error"})'


def prom(expr: str) -> float:
    try:
        r = requests.get(
            f"{PROM_URL}/api/v1/query", params={"query": expr}, timeout=4
        )
        res = r.json()["data"]["result"]
        if not res:
            return 0.0
        v = float(res[0]["value"][1])
        return 0.0 if v != v else v  # écarte les NaN
    except Exception:
        return 0.0


@app.get("/api/state")
def state():
    rps = prom(Q_RPS)
    lat = prom(Q_LAT)
    err = prom(Q_ERR)
    if err > ERR_WARN or lat > LAT_WARN:
        verdict = "incident"
    elif rps > 0:
        verdict = "nominal"
    else:
        verdict = "idle"
    return {
        "rps": round(rps, 2),
        "latency_p95_ms": round(lat * 1000, 1),
        "error_rate": round(err, 2),
        "success_total": int(prom(Q_SUCC)),
        "error_total": int(prom(Q_ERRTOT)),
        "verdict": verdict,
    }


@app.get("/api/services")
def services():
    """État up/down de chaque cible connue de Prometheus."""
    try:
        r = requests.get(f"{PROM_URL}/api/v1/query", params={"query": "up"}, timeout=4)
        out = []
        for item in r.json()["data"]["result"]:
            job = item["metric"].get("job", "?")
            out.append({"name": job, "up": item["value"][1] == "1"})
        return {"services": out}
    except Exception:
        return {"services": []}


@app.get("/api/incidents")
def incidents():
    """Historique des remédiations, le plus récent en premier."""
    try:
        r = requests.get(f"{REMEDIATOR_URL}/history", timeout=4)
        inc = r.json().get("incidents", [])
        return {"incidents": list(reversed(inc))}
    except Exception:
        return {"incidents": []}


@app.get("/api/health")
def health():
    return {"status": "ok", "service": "dashboard"}


# Le front statique est servi à la racine.
app.mount("/", StaticFiles(directory="static", html=True), name="static")
