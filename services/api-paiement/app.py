"""
API de paiement fictive — cœur métier du démonstrateur RESILIENCE-ALPHA.

Expose :
  GET  /health         -> sonde de vie
  POST /pay             -> traite une transaction fictive
  GET  /metrics         -> métriques Prometheus (lues par le detector)
  POST /admin/block     -> bloque une IP (appelé par le moteur de remédiation)
  GET  /admin/blocklist -> liste des IP bloquées

Défense en profondeur : une IP bloquée (identifiée à partir des logs par le
moteur de remédiation) est rejetée en 403 au niveau applicatif. Combiné au
blocage WAF, cela coupe réellement l'attaquant tout en laissant passer les
clients légitimes (autre IP source).

Mécanisme de dégradation : au-delà d'un certain nombre de transactions
concurrentes, le service ralentit puis renvoie des 503 — l'effet observable
du flood, repéré par la détection.

Aucune donnée bancaire réelle. Tout est simulé.
"""
import asyncio
import json
import os
import random

from fastapi import FastAPI, HTTPException, Request
from prometheus_client import Counter, Histogram, Gauge, make_asgi_app

app = FastAPI(title="API Paiement RESILIENCE-ALPHA")

PAYMENTS = Counter("payments_total", "Nombre de transactions traitées", ["status"])
LATENCY = Histogram("payment_latency_seconds", "Latence de traitement d'une transaction")
INFLIGHT = Gauge("payments_inflight", "Transactions en cours de traitement")
BLOCKED = Counter("payments_blocked_total", "Requêtes rejetées (IP bloquée)")

app.mount("/metrics", make_asgi_app())

SATURATION_THRESHOLD = int(os.getenv("SATURATION_THRESHOLD", "50"))
_inflight = 0

# Liste noire d'IP. Persistée sur disque pour SURVIVRE au redémarrage du
# conteneur pendant la remédiation (sinon le blocage serait perdu au restart).
BLOCKLIST_FILE = os.getenv("BLOCKLIST_FILE", "/app/blocklist.json")
BLOCKLIST: set[str] = set()


def _load_blocklist() -> None:
    try:
        with open(BLOCKLIST_FILE) as f:
            BLOCKLIST.update(json.load(f))
    except Exception:
        pass


def _save_blocklist() -> None:
    try:
        with open(BLOCKLIST_FILE, "w") as f:
            json.dump(sorted(BLOCKLIST), f)
    except Exception:
        pass


_load_blocklist()


@app.get("/health")
async def health():
    return {"status": "ok", "service": "api-paiement"}


@app.post("/admin/block")
async def admin_block(payload: dict):
    """Ajoute une IP à la liste noire (défense en profondeur)."""
    ip = (payload or {}).get("ip")
    if ip:
        BLOCKLIST.add(ip)
        _save_blocklist()
        return {"blocked": sorted(BLOCKLIST), "added": ip}
    return {"blocked": sorted(BLOCKLIST), "added": None}


@app.post("/admin/unblock")
async def admin_unblock(payload: dict):
    """Retire une IP de la liste noire (reset de démo). Sans 'ip' : vide tout."""
    ip = (payload or {}).get("ip")
    if ip:
        BLOCKLIST.discard(ip)
    else:
        BLOCKLIST.clear()
    _save_blocklist()
    return {"blocked": sorted(BLOCKLIST)}


@app.get("/admin/blocklist")
async def admin_blocklist():
    return {"blocked": sorted(BLOCKLIST)}


@app.post("/pay")
async def pay(request: Request, amount: float = 10.0):
    """
    Traite une transaction fictive.

    IP bloquée           -> rejet immédiat 403 (défense en profondeur).
    Charge normale       -> réponse rapide, statut success.
    Charge de saturation -> latence élevée, puis échecs 503 (service saturé).
    """
    client_ip = request.client.host if request.client else "inconnue"

    # Rejet des IP sur liste noire, AVANT tout traitement coûteux.
    if client_ip in BLOCKLIST:
        BLOCKED.inc()
        raise HTTPException(status_code=403, detail="IP bloquée")

    global _inflight
    _inflight += 1
    INFLIGHT.set(_inflight)
    try:
        with LATENCY.time():
            if _inflight > SATURATION_THRESHOLD:
                overload = _inflight / SATURATION_THRESHOLD
                await asyncio.sleep(min(2.0, 0.2 * overload))
                if random.random() < min(0.8, 0.2 * overload):
                    PAYMENTS.labels(status="error").inc()
                    raise HTTPException(status_code=503, detail="Service saturé")
            else:
                await asyncio.sleep(random.uniform(0.02, 0.08))

            PAYMENTS.labels(status="success").inc()
            return {"ok": True, "txid": random.randint(100000, 999999), "amount": amount}
    finally:
        _inflight -= 1
        INFLIGHT.set(_inflight)
