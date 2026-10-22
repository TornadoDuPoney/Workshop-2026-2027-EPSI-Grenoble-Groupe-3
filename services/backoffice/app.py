"""
Back-office sécurisé — RESILIENCE-ALPHA.

Authentification à deux facteurs :
  1. Saisie de l'identifiant -> reconnaissance faciale (service face-reco,
     caméra USB du PC Hôte). Si le visage ne correspond pas : identifiant
     remis à vide, 1 réessai, puis blocage 5 minutes.
  2. Si le visage est reconnu -> saisie du mot de passe.
     Mot de passe correct -> accès ; incorrect -> on recommence toute la phase.

Pilote une LED bicolore (ESP8266) selon l'état de l'authentification.
Gère les habilitations (enrôlement des visages, rôles).

Tout est local : la reconnaissance faciale ne quitte jamais la machine.
"""
import hashlib
import json
import os
import secrets
import time

import requests
from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles

app = FastAPI(title="Back-office RESILIENCE-ALPHA")

FACE_URL = os.getenv("FACE_URL", "http://face-reco:8000")
LED_URL = os.getenv("LED_URL", "")          # ex. http://192.168.1.50 (ESP32) ; vide = pas d'ESP
DATA_DIR = os.getenv("DATA_DIR", "/data")
USERS_PATH = os.path.join(DATA_DIR, "users.json")
LOCK_SECONDS = int(os.getenv("LOCK_SECONDS", "300"))      # 5 minutes
MAX_FACE_ATTEMPTS = int(os.getenv("MAX_FACE_ATTEMPTS", "2"))  # 1 essai + 1 réessai

os.makedirs(DATA_DIR, exist_ok=True)

# État d'authentification en mémoire : par utilisateur.
_attempts: dict[str, dict] = {}   # {user: {"face_fails": int, "locked_until": ts}}
_led_state = {"state": "off", "ts": time.time()}


# --- Habilitations (persistées) ------------------------------------------
def _load_users() -> dict:
    try:
        with open(USERS_PATH) as f:
            return json.load(f)
    except Exception:
        return {}


def _save_users(d: dict) -> None:
    with open(USERS_PATH, "w") as f:
        json.dump(d, f)


def _hash(pw: str, salt: str) -> str:
    return hashlib.sha256((salt + pw).encode()).hexdigest()


# --- LED (ESP8266) -------------------------------------------------------
def set_led(state: str) -> None:
    """Pilote la LED bicolore. Tolérant : si pas d'ESP configuré/joignable, on ignore."""
    _led_state.update(state=state, ts=time.time())
    if not LED_URL:
        return
    try:
        requests.post(f"{LED_URL}/led", json={"state": state}, timeout=2)
    except Exception:
        pass


# --- Verrouillage --------------------------------------------------------
def _locked_remaining(user: str) -> int:
    a = _attempts.get(user, {})
    rem = int(a.get("locked_until", 0) - time.time())
    return max(0, rem)


# --- Flux d'authentification ---------------------------------------------
@app.post("/api/identify")
def identify(payload: dict):
    user = (payload or {}).get("username", "").strip()
    users = _load_users()

    rem = _locked_remaining(user)
    if rem > 0:
        return {"step": "identify", "locked": True, "retry_in": rem,
                "message": f"Compte bloqué, réessayez dans {rem} s."}

    # Utilisateur inconnu : message générique (ne pas révéler), pas de caméra.
    if user not in users:
        return {"step": "identify", "message": "Identifiant ou visage non reconnu."}

    # Reconnaissance faciale via le service local (caméra USB du PC Hôte).
    try:
        r = requests.post(f"{FACE_URL}/verify", json={"user": user}, timeout=20)
        res = r.json()
    except Exception:
        set_led("red_solid")
        return {"step": "identify", "message": "Service de reconnaissance indisponible."}

    if res.get("recognized"):
        _attempts[user] = {"face_fails": 0, "locked_until": 0}
        set_led("green_blink")   # visage reconnu : vert clignotant jusqu'au mot de passe
        return {"step": "password", "message": "Visage reconnu. Saisissez votre mot de passe."}

    # Échec de reconnaissance.
    a = _attempts.setdefault(user, {"face_fails": 0, "locked_until": 0})
    a["face_fails"] += 1
    set_led("red_solid")          # non reconnu : rouge fixe 30 s (géré par l'ESP)
    if a["face_fails"] >= MAX_FACE_ATTEMPTS:
        a["locked_until"] = time.time() + LOCK_SECONDS
        a["face_fails"] = 0
        return {"step": "identify", "locked": True, "retry_in": LOCK_SECONDS,
                "message": f"Visage non reconnu. Compte bloqué {LOCK_SECONDS // 60} minutes."}
    return {"step": "identify", "message": "Visage non reconnu. Il vous reste 1 essai."}


@app.post("/api/password")
def password(payload: dict):
    user = (payload or {}).get("username", "").strip()
    pw = (payload or {}).get("password", "")
    users = _load_users()

    if _locked_remaining(user) > 0:
        return {"granted": False, "step": "identify", "message": "Compte bloqué."}

    u = users.get(user)
    if u and _hash(pw, u["salt"]) == u["pw_hash"]:
        set_led("green_solid")    # accès : vert fixe 30 s (géré par l'ESP) puis extinction
        token = secrets.token_hex(16)
        return {"granted": True, "role": u.get("role", "operateur"),
                "token": token, "message": "Accès autorisé."}

    # Mot de passe incorrect : on recommence toute la phase d'identification.
    set_led("red_blink")          # rouge : 10 clignotements (géré par l'ESP)
    return {"granted": False, "step": "identify",
            "message": "Mot de passe incorrect. Reprise de l'identification."}


# --- Gestion des habilitations ------------------------------------------
@app.get("/api/admin/users")
def list_users():
    users = _load_users()
    return {"users": [
        {"username": k, "role": v.get("role", "operateur"), "enrolled": v.get("enrolled", False)}
        for k, v in users.items()
    ]}


@app.post("/api/admin/users")
def add_user(payload: dict):
    user = (payload or {}).get("username", "").strip()
    pw = (payload or {}).get("password", "")
    role = (payload or {}).get("role", "operateur")
    if not user or not pw:
        raise HTTPException(status_code=400, detail="identifiant et mot de passe requis")
    users = _load_users()
    salt = secrets.token_hex(8)
    users[user] = {"pw_hash": _hash(pw, salt), "salt": salt, "role": role,
                   "enrolled": users.get(user, {}).get("enrolled", False)}
    _save_users(users)
    return {"ok": True, "username": user}


@app.delete("/api/admin/users/{user}")
def del_user(user: str):
    users = _load_users()
    users.pop(user, None)
    _save_users(users)
    try:
        requests.delete(f"{FACE_URL}/users/{user}", timeout=10)
    except Exception:
        pass
    return {"ok": True}


@app.post("/api/admin/enroll")
def enroll(payload: dict):
    """Enrôle le visage d'un utilisateur (capture via la caméra du PC Hôte)."""
    user = (payload or {}).get("username", "").strip()
    users = _load_users()
    if user not in users:
        raise HTTPException(status_code=404, detail="utilisateur inconnu")
    try:
        r = requests.post(f"{FACE_URL}/enroll", json={"user": user}, timeout=40)
        res = r.json()
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"service face-reco: {exc}")
    users[user]["enrolled"] = True
    _save_users(users)
    return {"ok": True, "enrolment": res}


@app.post("/api/cancel")
def cancel():
    """Annulation de la saisie ou déconnexion : on éteint le voyant physique."""
    set_led("off")
    return {"ok": True}


@app.get("/api/led")
def led_state():
    return _led_state


@app.get("/api/health")
def health():
    return {"status": "ok", "service": "backoffice"}


app.mount("/", StaticFiles(directory="static", html=True), name="static")
