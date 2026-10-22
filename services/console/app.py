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
# Le trafic légitime est généré par un conteneur DÉDIÉ (traffic-gen), avec sa
# propre IP, distincte de l'attaquant (la console). La remédiation bloque donc
# l'attaquant SANS couper le trafic légitime -> le dashboard repasse en NOMINAL.
TRAFFIC_GEN_URL = os.getenv("TRAFFIC_GEN_URL", "http://traffic-gen:8000")
REMEDIATOR_URL = os.getenv("REMEDIATOR_URL", "http://remediator:8000")
ATTACK_WORKERS = int(os.getenv("ATTACK_WORKERS", "80"))

# --- État du générateur d'attaque (le trafic normal est délégué à traffic-gen) --
_attack = {"threads": [], "stop": None, "running": False, "profile": None}
_lock = threading.Lock()

# Profils d'attaque — paramètres EXACTS de la campagne de résilience (6/6).
# "incident": True = doit déclencher la remédiation ; False = charge de contrôle
# légitime qui NE doit PAS déclencher (preuve que le système ne surréagit pas).
ATTACK_PROFILES = {
    "flood":    {"label": "Flood volumétrique",        "workers": 120, "duree": 18, "delai": 0.0,  "ramp": False, "incident": True},
    "burst":    {"label": "Burst intense",             "workers": 160, "duree": 15, "delai": 0.0,  "ramp": False, "incident": True},
    "montee":   {"label": "Montée progressive",        "workers": 140, "duree": 24, "delai": 0.0,  "ramp": True,  "incident": True},
    "pression": {"label": "Pression modérée soutenue", "workers": 85,  "duree": 16, "delai": 0.0,  "ramp": False, "incident": True},
    "legitime": {"label": "Charge légitime élevée",    "workers": 15,  "duree": 14, "delai": 0.08, "ramp": False, "incident": False},
    "sonde":    {"label": "Sonde discrète",            "workers": 3,   "duree": 10, "delai": 0.2,  "ramp": False, "incident": False},
}


def _attack_worker(stop_evt: threading.Event, delay: float = 0.0):
    """Martèle l'API tant que l'arrêt n'est pas demandé.
    `delay` espace les requêtes (sert aux charges de contrôle légitimes)."""
    sess = requests.Session()
    while not stop_evt.is_set():
        try:
            sess.post(f"{API_URL}/pay", params={"amount": 1}, timeout=3)
        except Exception:
            pass
        if delay:
            time.sleep(delay)


@app.get("/api/status")
def status():
    traffic = False
    try:
        traffic = bool(requests.get(f"{TRAFFIC_GEN_URL}/status", timeout=3).json().get("running"))
    except Exception:
        pass
    return {"attack": _attack["running"], "traffic": traffic}


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


def _run_profile(p: dict, stop: threading.Event) -> None:
    """Exécute un profil d'attaque : lève les workers (avec montée progressive
    éventuelle), maintient la charge jusqu'à la fin, puis coupe tout."""
    if p["ramp"]:
        # Montée progressive des workers sur 8 s, puis maintien jusqu'à la fin.
        step = max(8.0 / p["workers"], 0.005)
        start = time.time()
        for _ in range(p["workers"]):
            if stop.is_set():
                break
            threading.Thread(target=_attack_worker, args=(stop, p["delai"]), daemon=True).start()
            time.sleep(step)
        stop.wait(max(0.0, p["duree"] - (time.time() - start)))
    else:
        for _ in range(p["workers"]):
            threading.Thread(target=_attack_worker, args=(stop, p["delai"]), daemon=True).start()
        stop.wait(p["duree"])
    stop.set()
    with _lock:
        if _attack["stop"] is stop:
            _attack.update(threads=[], running=False, profile=None)


def _launch_profile(key: str) -> str:
    p = ATTACK_PROFILES.get(key)
    if not p:
        return "Profil d'attaque inconnu"
    with _lock:
        if _attack["running"]:
            return "Une attaque est déjà en cours — arrêtez-la d'abord"
        stop = threading.Event()
        _attack.update(threads=[], stop=stop, running=True, profile=key)
    threading.Thread(target=_run_profile, args=(p, stop), daemon=True).start()
    kind = "attaque" if p["incident"] else "charge de contrôle"
    return f"{p['label']} — {kind} lancée ({p['workers']} workers, {p['duree']} s)"


@app.get("/api/attack/profiles")
def attack_profiles():
    """Liste des profils (pour information / documentation)."""
    return {k: {"label": v["label"], "workers": v["workers"], "duree": v["duree"],
                "incident": v["incident"]} for k, v in ATTACK_PROFILES.items()}


@app.post("/api/attack/launch")
def attack_launch(payload: dict):
    """Lance un scénario d'attaque nommé (fidèle à la campagne, s'arrête seul)."""
    key = (payload or {}).get("profile", "")
    return {"attack": True, "message": _launch_profile(key)}


@app.post("/api/attack/start")
def attack_start():
    return {"attack": True, "message": _start_attack()}


@app.post("/api/attack/burst")
def attack_burst():
    """Attaque à durée limitée — idéale pour le Clip Chrono (cycle propre)."""
    return {"attack": True, "message": _start_attack(duration=20)}


@app.post("/api/reset")
def reset_demo():
    """Remet la démo à zéro entre deux scénarios : débloque les IP (sinon
    l'attaque suivante ne sature plus) ET vide la timeline des incidents."""
    faits = []
    try:
        requests.post(f"{API_URL}/admin/unblock", json={}, timeout=5)
        faits.append("IP débloquées")
    except Exception:
        faits.append("déblocage IP indisponible")
    try:
        requests.post(f"{REMEDIATOR_URL}/reset", timeout=5)
        faits.append("timeline réinitialisée")
    except Exception:
        faits.append("reset timeline indisponible")
    return {"ok": True, "message": "Réinitialisation — " + ", ".join(faits)}


@app.post("/api/attack/stop")
def attack_stop():
    with _lock:
        if _attack["stop"]:
            _attack["stop"].set()
        _attack.update(threads=[], running=False)
    return {"attack": False, "message": "Attaque arrêtée"}


@app.post("/api/traffic/start")
def traffic_start():
    """Démarre le trafic légitime (conteneur dédié traffic-gen, IP distincte)."""
    try:
        return requests.post(f"{TRAFFIC_GEN_URL}/start", timeout=5).json()
    except Exception as exc:
        return {"traffic": False, "message": f"Générateur de trafic injoignable : {exc}"}


@app.post("/api/traffic/stop")
def traffic_stop():
    try:
        return requests.post(f"{TRAFFIC_GEN_URL}/stop", timeout=5).json()
    except Exception as exc:
        return {"traffic": False, "message": f"Générateur de trafic injoignable : {exc}"}


@app.post("/api/test-payment")
def test_payment():
    """Transaction d'un CLIENT LÉGITIME : émise par traffic-gen (IP non bloquée)."""
    try:
        return requests.post(f"{TRAFFIC_GEN_URL}/once", timeout=8).json()
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
