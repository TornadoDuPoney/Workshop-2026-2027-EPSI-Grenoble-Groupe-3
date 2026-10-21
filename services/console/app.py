"""
Console de démonstration — RESILIENCE-ALPHA.

Pilote la démo par des boutons au lieu de commandes terminal :
  - démarrer / arrêter l'attaque (flood HTTP sur l'API)
  - démarrer / arrêter le trafic normal
  - envoyer une transaction de test

Les générateurs de charge tournent en threads d'arrière-plan, contrôlés par
des drapeaux d'arrêt. Tout cible le SI local ; aucun effet hors de la plateforme.

  GET  /                  -> page de la console
  GET  /api/status        -> état (attaque active ? trafic actif ?)
  POST /api/attack/start   | /api/attack/stop
  POST /api/traffic/start  | /api/traffic/stop
  POST /api/test-payment   -> une transaction unique
"""
import os
import threading
import time

import requests
from fastapi import FastAPI

app = FastAPI(title="Console RESILIENCE-ALPHA")

API_URL = os.getenv("API_URL", "http://api-paiement:8000")
REMEDIATOR_URL = os.getenv("REMEDIATOR_URL", "http://remediator:8000")
ATTACK_WORKERS = int(os.getenv("ATTACK_WORKERS", "80"))
TRAFFIC_RPS = int(os.getenv("TRAFFIC_RPS", "10"))

# --- État des générateurs de charge --------------------------------------
_attack = {"threads": [], "stop": None, "running": False}
_traffic = {"threads": [], "stop": None, "running": False}
_lock = threading.Lock()


def _attack_worker(stop_evt: threading.Event):
    """Martèle l'API tant que l'arrêt n'est pas demandé."""
    sess = requests.Session()
    while not stop_evt.is_set():
        try:
            sess.post(f"{API_URL}/pay", params={"amount": 1}, timeout=3)
        except Exception:
            pass


def _traffic_worker(stop_evt: threading.Event, delay: float):
    """Trafic régulier et léger."""
    sess = requests.Session()
    while not stop_evt.is_set():
        try:
            sess.post(f"{API_URL}/pay", params={"amount": 10}, timeout=3)
        except Exception:
            pass
        time.sleep(delay)


@app.get("/api/status")
def status():
    return {"attack": _attack["running"], "traffic": _traffic["running"]}


def _start_attack(duration: float | None = None) -> str:
    """Lance l'attaque ; si duration est fourni, elle s'arrête seule après."""
    with _lock:
        if _attack["running"]:
            return "Attaque déjà en cours"
        stop = threading.Event()
        threads = [threading.Thread(target=_attack_worker, args=(stop,), daemon=True)
                   for _ in range(ATTACK_WORKERS)]
        for t in threads:
            t.start()
        _attack.update(threads=threads, stop=stop, running=True)
    if duration:
        # Minuteur d'arrêt automatique (robuste : ferme CE jeu de threads).
        def _auto_stop(evt=stop):
            time.sleep(duration)
            evt.set()
            with _lock:
                if _attack["stop"] is evt:
                    _attack.update(threads=[], running=False)
        threading.Thread(target=_auto_stop, daemon=True).start()
        return f"Attaque courte lancée ({ATTACK_WORKERS} workers, {int(duration)} s)"
    return f"Attaque lancée ({ATTACK_WORKERS} workers)"


@app.post("/api/attack/start")
def attack_start():
    return {"attack": True, "message": _start_attack()}


@app.post("/api/attack/burst")
def attack_burst():
    """Attaque à durée limitée — idéale pour le Clip Chrono (cycle propre)."""
    return {"attack": True, "message": _start_attack(duration=20)}


@app.post("/api/attack/stop")
def attack_stop():
    with _lock:
        if _attack["stop"]:
            _attack["stop"].set()
        _attack.update(threads=[], running=False)
    return {"attack": False, "message": "Attaque arrêtée"}


@app.post("/api/traffic/start")
def traffic_start():
    with _lock:
        if _traffic["running"]:
            return {"traffic": True, "message": "Trafic déjà actif"}
        stop = threading.Event()
        threads = [threading.Thread(target=_traffic_worker, args=(stop, 1.0), daemon=True)
                   for _ in range(TRAFFIC_RPS)]
        for t in threads:
            t.start()
        _traffic.update(threads=threads, stop=stop, running=True)
    return {"traffic": True, "message": f"Trafic normal lancé (~{TRAFFIC_RPS} req/s)"}


@app.post("/api/traffic/stop")
def traffic_stop():
    with _lock:
        if _traffic["stop"]:
            _traffic["stop"].set()
        _traffic.update(threads=[], running=False)
    return {"traffic": False, "message": "Trafic normal arrêté"}


@app.post("/api/test-payment")
def test_payment():
    try:
        r = requests.post(f"{API_URL}/pay", params={"amount": 5}, timeout=5)
        if r.status_code == 200 and r.json().get("ok"):
            return {"ok": True, "message": f"Transaction réussie (réf. {r.json().get('txid')})"}
        return {"ok": False, "message": f"Transaction refusée (HTTP {r.status_code})"}
    except Exception as exc:
        return {"ok": False, "message": f"Service injoignable : {exc}"}


@app.post("/api/ask")
def ask(payload: dict):
    """Relaie une question à l'assistant RAG (remediator) et renvoie sa réponse."""
    question = (payload or {}).get("question", "").strip()
    if not question:
        return {"answer": None, "error": "question vide"}
    try:
        r = requests.post(
            f"{REMEDIATOR_URL}/ask", json={"question": question}, timeout=180
        )
        return r.json()
    except Exception as exc:
        return {"answer": None, "error": f"assistant injoignable : {exc}"}


@app.get("/api/health")
def health():
    return {"status": "ok", "service": "console"}


from fastapi.staticfiles import StaticFiles  # noqa: E402
app.mount("/", StaticFiles(directory="static", html=True), name="static")
