"""
Générateur de trafic légitime — RESILIENCE-ALPHA.

Tourne dans SON PROPRE conteneur, donc avec sa PROPRE adresse IP, distincte de
celle de l'attaquant (la console). C'est le point clé : quand la remédiation
bloque l'IP de l'attaquant, ce trafic légitime n'est PAS concerné et continue
de passer — le dashboard repasse donc correctement en NOMINAL après l'incident
(au lieu de retomber en « EN ATTENTE »).

Il simule des clients de confiance et cible l'API de paiement.

  POST /start   -> démarre le trafic régulier
  POST /stop    -> arrête le trafic
  GET  /status  -> trafic actif ?
  POST /once    -> une transaction unique (client légitime)
"""
import os
import threading
import time

import requests
from fastapi import FastAPI

app = FastAPI(title="Traffic-gen RESILIENCE-ALPHA")

API_URL = os.getenv("API_URL", "http://api-paiement:8000")
TRAFFIC_RPS = int(os.getenv("TRAFFIC_RPS", "10"))

_state = {"stop": None, "running": False}
_lock = threading.Lock()


def _worker(stop_evt: threading.Event, delay: float):
    sess = requests.Session()
    while not stop_evt.is_set():
        try:
            sess.post(f"{API_URL}/pay", params={"amount": 10}, timeout=3)
        except Exception:
            pass
        time.sleep(delay)


@app.post("/start")
def start():
    with _lock:
        if _state["running"]:
            return {"running": True, "message": "Trafic normal déjà actif"}
        stop = threading.Event()
        for _ in range(TRAFFIC_RPS):
            threading.Thread(target=_worker, args=(stop, 1.0), daemon=True).start()
        _state.update(stop=stop, running=True)
    return {"running": True, "message": f"Trafic normal lancé (~{TRAFFIC_RPS} req/s)"}


@app.post("/stop")
def stop():
    with _lock:
        if _state["stop"]:
            _state["stop"].set()
        _state.update(stop=None, running=False)
    return {"running": False, "message": "Trafic normal arrêté"}


@app.get("/status")
def status():
    return {"running": _state["running"]}


@app.post("/once")
def once():
    try:
        r = requests.post(f"{API_URL}/pay", params={"amount": 5}, timeout=5)
        if r.status_code == 200 and r.json().get("ok"):
            return {"ok": True, "message": f"Transaction réussie (réf. {r.json().get('txid')})"}
        return {"ok": False, "message": f"Transaction refusée (HTTP {r.status_code})"}
    except Exception as exc:
        return {"ok": False, "message": f"Service injoignable : {exc}"}


@app.get("/health")
def health():
    return {"status": "ok", "service": "traffic-gen"}
