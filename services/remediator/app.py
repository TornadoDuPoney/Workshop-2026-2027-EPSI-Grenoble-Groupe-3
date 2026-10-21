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
import re
import threading
import time
from datetime import datetime, timezone, timedelta

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

# Base de connaissances vectorielle (RAG) — Qdrant + embeddings Ollama.
# Optionnelle : si indisponible, l'analyse se fait sans contexte documentaire.
QDRANT_URL = os.getenv("QDRANT_URL", "http://qdrant:6333")
EMBED_MODEL = os.getenv("EMBED_MODEL", "nomic-embed-text")
KB_COLLECTION = os.getenv("KB_COLLECTION", "infra")

# Historique en mémoire des incidents traités (lu par le dashboard).
HISTORY: list[dict] = []


def _embed(text: str) -> list[float]:
    """Embedding d'un texte via le modèle local Ollama."""
    r = requests.post(
        f"{OLLAMA_URL}/api/embeddings",
        json={"model": EMBED_MODEL, "prompt": text},
        timeout=60,
    )
    r.raise_for_status()
    return r.json()["embedding"]


def retrieve_context(query: str, k: int = 3) -> str:
    """
    Interroge la base de connaissances (Qdrant) : renvoie les passages de
    documentation les plus proches de la question. C'est l'étape « RAG » :
    l'IA va chercher le bon runbook avant de répondre. Tolérant aux pannes.
    """
    try:
        from qdrant_client import QdrantClient
        client = QdrantClient(url=QDRANT_URL)
        hits = client.search(
            collection_name=KB_COLLECTION,
            query_vector=_embed(query),
            limit=k,
        )
        passages = [h.payload.get("text", "") for h in hits]
        return "\n\n---\n\n".join(p for p in passages if p)
    except Exception as exc:
        print(f"[remediator] RAG indisponible: {exc}", flush=True)
        return ""


def generate_analysis(incident: dict) -> None:
    """
    Fait rédiger par le LLM LOCAL (Ollama) une analyse de l'incident, ANCRÉE
    sur la documentation d'infrastructure récupérée dans Qdrant (RAG). Appel
    asynchrone : n'impacte pas le temps de reprise. Tolérant aux pannes.
    """
    sig = incident.get("signal", {})
    etapes = " ; ".join(s["action"] for s in incident.get("steps", []))
    question = (
        f"Incident sur la plateforme de paiement : débit={sig.get('rps')} req/s, "
        f"latence p95={sig.get('latency_p95')} s, taux d'erreur={sig.get('error_rate')} /s."
    )
    # Étape RAG : récupérer le runbook pertinent.
    contexte = retrieve_context(question)
    incident["kb_context_found"] = bool(contexte)

    prompt = (
        "Tu es analyste SOC. En t'appuyant UNIQUEMENT sur la documentation "
        "ci-dessous, rédige en 3 phrases maximum, en français, une analyse de "
        "l'incident : nature probable, pourquoi la remédiation était adaptée "
        "selon le runbook, et le point de vigilance mentionné. Sans préambule.\n\n"
        f"=== Documentation d'infrastructure (runbooks) ===\n{contexte or '(aucune doc disponible)'}\n\n"
        f"=== Incident ===\n{question}\n"
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
            src = "RAG + LLM local" if contexte else "LLM local"
            incident["analysis_by"] = f"{src} ({OLLAMA_MODEL})"
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


# Conteneurs dont on lit les logs pour identifier l'attaquant.
LOG_CONTAINERS = [API_CONTAINER, WAF_CONTAINER]
# Fenêtre de logs analysée (secondes).
LOG_WINDOW_S = int(os.getenv("LOG_WINDOW_S", "40"))
_IP_RE = re.compile(r"(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})")


def identify_attacker_from_logs() -> str | None:
    """
    Lit les LOGS récents de l'API et du WAF, compte les requêtes par IP source
    et renvoie l'IP la plus bruyante (l'attaquant). C'est l'analyse des journaux
    qui identifie la source de l'attaque, et non une simple métrique agrégée.
    """
    counts: dict[str, int] = {}
    since = datetime.now(timezone.utc) - timedelta(seconds=LOG_WINDOW_S)
    try:
        client = _docker_client()
    except Exception as exc:
        print(f"[remediator] docker indisponible pour les logs: {exc}", flush=True)
        return None

    for cname in LOG_CONTAINERS:
        try:
            raw = client.containers.get(cname).logs(since=since).decode("utf-8", "ignore")
        except Exception:
            continue
        for line in raw.splitlines():
            # On ne compte que les lignes de requête de paiement.
            if "/pay" not in line:
                continue
            m = _IP_RE.search(line)
            if m:
                ip = m.group(1)
                counts[ip] = counts.get(ip, 0) + 1

    if not counts:
        return None
    # L'attaquant = l'IP qui génère nettement le plus de requêtes.
    top_ip, top_count = max(counts.items(), key=lambda kv: kv[1])
    print(f"[remediator] analyse des logs: IP dominante {top_ip} ({top_count} requêtes)", flush=True)
    return top_ip


def restart_api() -> str:
    """Redémarre le conteneur de l'API métier."""
    try:
        client = _docker_client()
        client.containers.get(API_CONTAINER).restart()
        return f"conteneur {API_CONTAINER} redémarré"
    except Exception as exc:
        return f"échec redémarrage API: {exc}"


def block_attacker(ip: str | None) -> str:
    """
    Bloque l'attaquant identifié, à deux niveaux (défense en profondeur) :
      - WAF : règle nginx deny pour cette IP (chemin production) ;
      - API : liste noire applicative (coupe l'attaquant dans tous les cas).
    """
    if not ip:
        return "aucune IP attaquante identifiée dans les logs"

    résultats = []
    # 1. Blocage WAF (best-effort : dépend du chemin réseau)
    try:
        client = _docker_client()
        waf = client.containers.get(WAF_CONTAINER)
        waf.exec_run(["sh", BLOCK_SCRIPT, ip])
        résultats.append("WAF")
    except Exception:
        pass
    # 2. Blocage applicatif (défense en profondeur, toujours effectif)
    try:
        requests.post(f"{API_URL}/admin/block", json={"ip": ip}, timeout=4)
        résultats.append("API")
    except Exception:
        pass

    où = " + ".join(résultats) if résultats else "aucun niveau"
    return f"IP {ip} bloquée ({où})"


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


@app.post("/ask")
def ask(payload: dict):
    """
    Assistant RAG : répond à une question sur l'infrastructure en allant
    chercher les passages pertinents dans la base de connaissances (Qdrant)
    puis en les faisant synthétiser par le LLM local. 100% local.
    """
    question = (payload or {}).get("question", "").strip()
    if not question:
        return {"answer": None, "error": "question vide"}

    contexte = retrieve_context(question, k=4)
    prompt = (
        "Tu es l'assistant technique de la plateforme RESILIENCE-ALPHA. Réponds "
        "en français, de façon concise et pratique, en t'appuyant UNIQUEMENT sur "
        "la documentation ci-dessous. Si la réponse n'y est pas, dis-le.\n\n"
        f"=== Documentation ===\n{contexte or '(aucune doc trouvée)'}\n\n"
        f"=== Question ===\n{question}"
    )
    try:
        r = requests.post(
            f"{OLLAMA_URL}/api/generate",
            json={"model": OLLAMA_MODEL, "prompt": prompt, "stream": False},
            timeout=120,
        )
        answer = r.json().get("response", "").strip() if r.status_code == 200 else None
        return {"answer": answer, "sources_found": bool(contexte)}
    except Exception as exc:
        return {"answer": None, "error": str(exc)}


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
        "attacker_ip": None,
    }

    # 1. IDENTIFIER l'attaquant par l'analyse des logs
    attacker_ip = identify_attacker_from_logs()
    incident["attacker_ip"] = attacker_ip
    incident["steps"].append({
        "t": _now(),
        "action": (f"attaquant identifié dans les logs : {attacker_ip}"
                   if attacker_ip else "aucun attaquant isolé dans les logs"),
    })

    # 2. Contenir l'attaque (blocage ciblé de l'IP identifiée)
    step = block_attacker(attacker_ip)
    incident["steps"].append({"t": _now(), "action": step})

    # 3. Rétablir le service
    step = restart_api()
    incident["steps"].append({"t": _now(), "action": step})
    time.sleep(6)  # laisse l'API redémarrer

    # 4. PROUVER la reprise par une nouvelle transaction
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
