"""
Service de reconnaissance faciale — RESILIENCE-ALPHA.

Vérification d'identité 1:1 par EMBEDDINGS faciaux (réseau SFace d'OpenCV) :
chaque visage est converti en un vecteur de 128 dimensions ; on compare la
similarité cosinus entre le visage enrôlé et le visage présenté. Cette méthode
distingue réellement les identités (contrairement à LBPH, qui acceptait tout
visage quand un seul utilisateur était enrôlé).

Détection : YuNet. Reconnaissance : SFace. Les deux tournent LOCALEMENT sur le
PC Hôte, avec la caméra USB. Aucune donnée biométrique ne quitte la machine.

  POST /enroll   {user}  -> capture plusieurs visages, stocke l'empreinte moyenne
  POST /verify   {user}  -> capture un visage et le compare à l'empreinte (1:1)
  GET  /users            -> utilisateurs enrôlés
  DELETE /users/{user}   -> supprime un utilisateur
  GET  /camera           -> test d'accès caméra
"""
import json
import os
import threading
import time

import cv2
import numpy as np
from fastapi import FastAPI, HTTPException

app = FastAPI(title="Face-Reco RESILIENCE-ALPHA")

CAMERA_INDEX = int(os.getenv("CAMERA_INDEX", "0"))
DATA_DIR = os.getenv("DATA_DIR", "/data")
PRINTS_PATH = os.path.join(DATA_DIR, "faceprints.json")   # {user: [128 floats]}
DETECT_MODEL = os.getenv("DETECT_MODEL", "/models/yunet.onnx")
RECO_MODEL = os.getenv("RECO_MODEL", "/models/sface.onnx")
# Similarité cosinus minimale pour accepter : SFace recommande 0.363.
# Plus HAUT = plus strict (moins de faux positifs). 0.40 = prudent.
COSINE_MIN = float(os.getenv("COSINE_MIN", "0.40"))
ENROLL_SAMPLES = int(os.getenv("ENROLL_SAMPLES", "15"))

os.makedirs(DATA_DIR, exist_ok=True)
_lock = threading.Lock()
_detector = cv2.FaceDetectorYN.create(DETECT_MODEL, "", (320, 320), 0.9, 0.3, 5000)
_recognizer = cv2.FaceRecognizerSF.create(RECO_MODEL, "")


def _load_prints() -> dict:
    try:
        with open(PRINTS_PATH) as f:
            return json.load(f)
    except Exception:
        return {}


def _save_prints(d: dict) -> None:
    with open(PRINTS_PATH, "w") as f:
        json.dump(d, f)


def _largest_face(frame):
    """Détecte le plus grand visage de l'image ; renvoie la ligne YuNet ou None."""
    h, w = frame.shape[:2]
    _detector.setInputSize((w, h))
    _, faces = _detector.detect(frame)
    if faces is None or len(faces) == 0:
        return None
    # le plus grand (colonnes 2,3 = largeur,hauteur)
    return max(faces, key=lambda f: f[2] * f[3])


def _feature(frame, face) -> np.ndarray:
    """Aligne/recadre le visage et calcule son empreinte (128-d, normalisée)."""
    aligned = _recognizer.alignCrop(frame, np.asarray(face, dtype=np.float32).reshape(1, -1))
    feat = _recognizer.feature(aligned).flatten().astype(np.float32)
    n = np.linalg.norm(feat)
    return feat / n if n > 0 else feat


def _capture_features(n: int, timeout: float):
    """Capture jusqu'à n empreintes de visage depuis la caméra."""
    cap = cv2.VideoCapture(CAMERA_INDEX)
    if not cap.isOpened():
        raise HTTPException(status_code=503, detail="Caméra inaccessible sur le PC Hôte")
    feats = []
    start = time.time()
    try:
        while len(feats) < n and time.time() - start < timeout:
            ok, frame = cap.read()
            if not ok:
                continue
            face = _largest_face(frame)
            if face is not None:
                feats.append(_feature(frame, face))
            time.sleep(0.05)
    finally:
        cap.release()
    return feats


def _cosine(a, b) -> float:
    return float(np.dot(a, b))   # vecteurs déjà normalisés


@app.get("/camera")
def camera_test():
    cap = cv2.VideoCapture(CAMERA_INDEX)
    ok = cap.isOpened()
    cap.release()
    return {"camera_disponible": ok, "index": CAMERA_INDEX}


@app.get("/users")
def users():
    return {"users": sorted(_load_prints().keys())}


@app.delete("/users/{user}")
def delete_user(user: str):
    with _lock:
        prints = _load_prints()
        prints.pop(user, None)
        _save_prints(prints)
    return {"users": sorted(_load_prints().keys())}


@app.post("/enroll")
def enroll(payload: dict):
    user = (payload or {}).get("user", "").strip()
    if not user:
        raise HTTPException(status_code=400, detail="identifiant manquant")
    feats = _capture_features(ENROLL_SAMPLES, timeout=20.0)
    if len(feats) < 3:
        raise HTTPException(status_code=422, detail="visage insuffisamment détecté, réessayez")
    # Empreinte de référence = moyenne normalisée des captures.
    mean = np.mean(feats, axis=0)
    mean = mean / np.linalg.norm(mean)
    with _lock:
        prints = _load_prints()
        prints[user] = mean.tolist()
        _save_prints(prints)
    return {"user": user, "echantillons_captures": len(feats)}


@app.post("/verify")
def verify(payload: dict):
    user = (payload or {}).get("user", "").strip()
    if not user:
        raise HTTPException(status_code=400, detail="identifiant manquant")
    prints = _load_prints()
    if user not in prints:
        return {"recognized": False, "reason": "utilisateur non enrôlé"}

    ref = np.array(prints[user], dtype=np.float32)
    feats = _capture_features(1, timeout=6.0)
    if not feats:
        return {"recognized": False, "reason": "aucun visage détecté"}

    score = _cosine(feats[0], ref)
    recognized = score >= COSINE_MIN
    return {
        "recognized": bool(recognized),
        "user": user,
        "similarite": round(score, 3),
        "seuil": COSINE_MIN,
    }


@app.get("/health")
def health():
    return {"status": "ok", "service": "face-reco"}
