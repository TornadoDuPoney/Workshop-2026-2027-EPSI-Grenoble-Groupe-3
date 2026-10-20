"""
Site de paiement fictif — RESILIENCE-ALPHA.

Petite banque de démonstration. Le front (React + Tailwind) envoie des
paiements ; ce backend les relaie vers l'API métier (api-paiement) et tient
un compte + un historique en mémoire. AUCUNE sécurité bancaire réelle : tout
est fictif, le but est de montrer que les transactions passent de nouveau
après un incident.

  GET  /              -> page de la banque
  GET  /api/account   -> solde + historique
  POST /api/pay       -> tente un paiement (relais vers api-paiement)
"""
import os
import random
import threading

import requests
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

app = FastAPI(title="Banque RESILIENCE-ALPHA")

API_URL = os.getenv("API_URL", "http://api-paiement:8000")

# État fictif, en mémoire (remis à zéro au redémarrage du conteneur).
_lock = threading.Lock()
STATE = {
    "holder": "Compte de démonstration",
    "iban": "FR76 0000 0000 0000 0000 000",
    "balance": 5000.00,          # solde de départ fictif
    "history": [],               # transactions, la plus récente en premier
}

BENEFICIAIRES = ["Boulangerie Martin", "EDF", "Loyer SCI Alpha", "Amazon", "Spotify"]


class PaymentIn(BaseModel):
    amount: float
    beneficiary: str = "Bénéficiaire"


@app.get("/api/account")
def account():
    with _lock:
        return {
            "holder": STATE["holder"],
            "iban": STATE["iban"],
            "balance": round(STATE["balance"], 2),
            "history": STATE["history"][:20],
        }


@app.post("/api/pay")
def pay(p: PaymentIn):
    """
    Tente une transaction via l'API métier.
    Succès -> débit du compte + ligne d'historique.
    Échec (service saturé/indisponible) -> transaction refusée, compte intact.
    """
    entry = {
        "beneficiary": p.beneficiary or "Bénéficiaire",
        "amount": round(float(p.amount), 2),
        "status": "échouée",
        "txid": None,
    }
    try:
        r = requests.post(f"{API_URL}/pay", params={"amount": p.amount}, timeout=4)
        if r.status_code == 200 and r.json().get("ok"):
            entry["status"] = "réussie"
            entry["txid"] = r.json().get("txid")
            with _lock:
                STATE["balance"] -= entry["amount"]
        else:
            entry["reason"] = "Service de paiement indisponible"
    except Exception:
        entry["reason"] = "Service de paiement injoignable"

    with _lock:
        STATE["history"].insert(0, entry)
        STATE["history"] = STATE["history"][:50]
        balance = round(STATE["balance"], 2)

    return JSONResponse({"transaction": entry, "balance": balance})


@app.get("/api/health")
def health():
    return {"status": "ok", "service": "frontend"}


app.mount("/", StaticFiles(directory="static", html=True), name="static")
