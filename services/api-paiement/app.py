"""
API de paiement fictive — coeur metier du demonstrateur RESILIENCE-ALPHA.
Degradation sous charge concurrente : au-dela du seuil, latence haute puis 503.
Endpoints async : la saturation est mesuree fidelement meme sous flood.
"""
import asyncio
import os
import random

from fastapi import FastAPI, HTTPException
from prometheus_client import Counter, Histogram, Gauge, make_asgi_app

app = FastAPI(title="API Paiement RESILIENCE-ALPHA")

PAYMENTS = Counter("payments_total", "Transactions traitees", ["status"])
LATENCY = Histogram("payment_latency_seconds", "Latence de traitement")
INFLIGHT = Gauge("payments_inflight", "Transactions en cours")

app.mount("/metrics", make_asgi_app())

SATURATION_THRESHOLD = int(os.getenv("SATURATION_THRESHOLD", "50"))
_inflight = 0


@app.get("/health")
async def health():
    return {"status": "ok", "service": "api-paiement"}


@app.post("/pay")
async def pay(amount: float = 10.0):
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
                    raise HTTPException(status_code=503, detail="Service sature")
            else:
                await asyncio.sleep(random.uniform(0.02, 0.08))
            PAYMENTS.labels(status="success").inc()
            return {"ok": True, "txid": random.randint(100000, 999999), "amount": amount}
    finally:
        _inflight -= 1
        INFLIGHT.set(_inflight)
