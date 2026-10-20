"""
Moteur de remédiation — RESILIENCE-ALPHA.

Reçoit une alerte du detector, exécute les actions correctives SANS
intervention humaine, puis PROUVE la reprise en relançant une transaction
de contrôle. L'historique est exposé pour le dashboard de supervision.

Point sensible (à justifier dans le dossier) : ce service a accès au socket
Docker pour pouvoir redémarrer des conteneurs. Il est donc isolé sur un
réseau dédié et n'expose aucune interface d'administration ouverte.
"""
import os
import threading
import time
from datetime import datetime, timezone

import requests
from fastapi import FastAPI

app = FastAPI(title="Remediator RESILIENCE-ALPHA")

API_URL = os.getenv("API_URL", "http://api-paiement:8000")
API_CONTAINER = os.getenv("API_CONTAINER", "resilience-api-paiement")
WAF_CONTAINER = os.getenv("WAF_CONTAINER", "resilience-waf")
BLOCK_SCRIPT = os.getenv("BLOCK_SCRIPT", "/scripts/block_attacker.sh")

# LLM local (Ollama) — analyse d'incident. Optionnel : si indisponible,
# la remédiation fonctionne quand même, l'analyse reste simplement vide.
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://ollama:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.2:3b")

# Historique en mémoire des incidents traités (lu par le dashboard).
HISTORY: list[dict] = []


def generate_analysis(incident: dict) -> None:
    """
    Fait rédiger par le LLM LOCAL (Ollama) une courte analyse de l'incident,
    puis la range dans incident['analysis']. Appel asynchrone : n'impacte pas
    le temps de reprise. Tolérant aux pannes (LLM absent, lent, modèle manquant).
    """
    sig = incident.get("signal", {})
    etapes = " ; ".join(s["action"] for s in incident.get("steps", []))
    prompt = (
        "Tu es analyste SOC. Rédige en 3 phrases maximum, en français, une analyse "
        "d'un incident de cybersécurité sur une plateforme de paiement. "
        "Indique la nature probable de l'incident, pourquoi la remédiation était "
        "adaptée, et un point de vigilance. Ne donne que l'analyse, sans préambule.\n\n"
        f"Métriques au déclenchement : débit={sig.get('rps')} req/s, "
        f"latence p95={sig.get('latency_p95')} s, taux d'erreur={sig.get('error_rate')} /s.\n"
        f"Actions automatiques exécutées : {etapes}.\n"
        f"Reprise confirmée : {'oui' if incident.get('recovered') else 'non'}."
    )
    try:
        r = requests.post(
            f"{OLLAMA_URL}/api/generate",
            json={"model": OLLAMA_MODEL, "prompt": prompt, "stream": False},
            timeout=120,
        )
        if r.status_code == 200:
            incident["analysis"] = r.json().get("response", "").strip()
            incident["analysis_by"] = f"LLM local ({OLLAMA_MODEL})"
        else:
            incident["analysis"] = None
    except Exception as exc:
        print(f"[remediator] analyse LLM indisponible: {exc}", flush=True)
        incident["analysis"] = None


def _docker_client():
    """Client Docker, isolé dans une fonction pour faciliter les tests."""
    import docker
    return docker.from_env()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def restart_api() -> str:
    """Redémarre le conteneur de l'API métier."""
    try:
        client = _docker_client()
        client.containers.get(API_CONTAINER).restart()
        return f"conteneur {API_CONTAINER} redémarré"
    except Exception as exc:
        return f"échec redémarrage API: {exc}"


def block_attacker() -> str:
    """Active la règle de blocage de l'attaquant au niveau du WAF."""
    try:
        client = _docker_client()
        waf = client.containers.get(WAF_CONTAINER)
        waf.exec_run(["sh", BLOCK_SCRIPT])
        return "IP attaquant bloquée au WAF"
    except Exception as exc:
        return f"blocage WAF indisponible: {exc}"


def control_transaction() -> bool:
    """
    PREUVE de reprise : relance une transaction fictive après remédiation.
    On réessaie quelques fois car l'API vient de redémarrer.
    """
    for attempt in range(6):
        try:
            r = requests.post(
                f"{API_URL}/pay", params={"amount": 1}, timeout=5
            )
            if r.status_code == 200 and r.json().get("ok"):
                return True
        except Exception:
            pass
        time.sleep(2)
    return False


@app.get("/health")
def health():
    return {"status": "ok", "service": "remediator"}


@app.get("/history")
def history():
    """Historique des remédiations — consommé par le dashboard."""
    return {"incidents": HISTORY}


@app.post("/alert")
def remediate(payload: dict):
    """
    Séquence de remédiation automatique.
    Chaque étape est horodatée pour une timeline lisible sur le dashboard.
    """
    incident = {
        "detected_at": _now(),
        "signal": payload,
        "steps": [],
        "recovered": False,
    }

    # 1. Contenir l'attaque
    step = block_attacker()
    incident["steps"].append({"t": _now(), "action": step})

    # 2. Rétablir le service
    step = restart_api()
    incident["steps"].append({"t": _now(), "action": step})
    time.sleep(6)  # laisse l'API redémarrer

    # 3. PROUVER la reprise par une nouvelle transaction
    ok = control_transaction()
    incident["steps"].append(
        {"t": _now(), "action": f"transaction de contrôle: {'RÉUSSIE' if ok else 'ÉCHOUÉE'}"}
    )
    incident["recovered"] = ok
    incident["recovered_at"] = _now()
    incident["analysis"] = "Analyse en cours par le LLM local…"

    HISTORY.append(incident)
    # L'analyse LLM tourne en arrière-plan : la réponse est renvoyée tout de
    # suite, l'analyse viendra enrichir l'incident dès qu'elle est prête.
    threading.Thread(target=generate_analysis, args=(incident,), daemon=True).start()

    print(f"[remediator] incident traité, recovered={ok}", flush=True)
    return incident
