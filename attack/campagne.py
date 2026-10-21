"""
Campagne de tests de résilience — RESILIENCE-ALPHA.

Enchaîne plusieurs profils d'attaque (et des cas de contrôle légitimes) et
vérifie, pour chacun, si le système a détecté l'anomalie et s'est rétabli.
Produit un tableau de résultats et un rapport Markdown pour le dossier.

Objectif : prouver la robustesse de la détection sur plusieurs scénarios,
ET l'absence de faux positifs sur une charge légitime.

Usage (depuis la racine, venv actif, plateforme démarrée) :
    python attack/campagne.py
    python attack/campagne.py --target http://localhost:8000/pay --rapport docs/campagne.md

Le script parle à l'API (débloquer entre scénarios) et au dashboard
(lire le verdict et l'historique d'incidents).
"""
import argparse
import os
import subprocess
import threading
import time

import requests

# Dossier docker compose (pour réinitialiser l'état entre scénarios).
_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
COMPOSE_DIR = os.path.join(_REPO, "infra", "compose")

API = "http://localhost:8000"       # api-paiement (admin + cible)
DASH = "http://localhost:8050"      # dashboard (état + incidents)
TARGET = f"{API}/pay"


def unblock_all():
    try:
        requests.post(f"{API}/admin/unblock", json={}, timeout=4)
    except Exception:
        pass


def state():
    try:
        return requests.get(f"{DASH}/api/state", timeout=4).json()
    except Exception:
        return {"verdict": "?", "latency_p95_ms": 0, "error_rate": 0, "rps": 0}


def incident_count():
    try:
        return len(requests.get(f"{DASH}/api/incidents", timeout=4).json().get("incidents", []))
    except Exception:
        return 0


def reset_state():
    """
    Remet la plateforme à zéro AVANT chaque scénario, pour des mesures
    indépendantes : débloque les IP, puis redémarre le detector (vide son
    cooldown) et l'API (vide blocklist mémoire + compteurs de métriques).
    Sans ça, le cooldown ou une IP bloquée d'un scénario fausse le suivant.
    """
    unblock_all()
    try:
        subprocess.run(
            ["docker", "compose", "restart", "detector", "api-paiement"],
            cwd=COMPOSE_DIR, capture_output=True, timeout=60,
        )
    except Exception as exc:
        print(f"  (reset: redémarrage impossible: {exc})", flush=True)
    time.sleep(4)        # laisser les conteneurs repartir
    unblock_all()        # la blocklist persistée est rechargée vide


def wait_until_calm(max_wait=60):
    """
    Attend que la plateforme soit revenue au calme AVANT de mesurer un scénario.
    Indispensable : les métriques sont lissées sur 30 s, donc il faut laisser la
    fenêtre se vider des données du scénario précédent pour partir d'une base
    propre (sinon un résidu d'attaque fausserait le cas de contrôle suivant).
    """
    calm = 0
    deadline = time.time() + max_wait
    while time.time() < deadline:
        if state().get("verdict") in ("nominal", "idle"):
            calm += 1
            if calm >= 2:
                return True
        else:
            calm = 0
        time.sleep(3)
    return False


def generate_load(workers, duration, delay, ramp, ramp_time=8.0):
    """
    Génère la charge : `workers` threads frappant l'API pendant `duration` s.
    ramp=True : montée progressive des workers sur `ramp_time` secondes, PUIS
    maintien de la pleine charge jusqu'à la fin de `duration` (attaque qui
    monte puis se maintient — le palier est ce qui rend l'anomalie détectable).
    """
    stop = threading.Event()

    def worker():
        s = requests.Session()
        while not stop.is_set():
            try:
                s.post(TARGET, params={"amount": 1}, timeout=3)
            except Exception:
                pass
            if delay:
                time.sleep(delay)

    threads = []
    if ramp:
        step = max(ramp_time / workers, 0.005)
        start = time.time()
        for _ in range(workers):
            t = threading.Thread(target=worker, daemon=True)
            t.start()
            threads.append(t)
            time.sleep(step)
        # Palier : on maintient la pleine charge le temps restant.
        time.sleep(max(0, duration - (time.time() - start)))
    else:
        for _ in range(workers):
            t = threading.Thread(target=worker, daemon=True)
            t.start()
            threads.append(t)
        time.sleep(duration)
    stop.set()


def run_scenario(sc):
    """
    Lance un scénario et mesure la RÉACTION DU DÉTECTEUR.
    « Détecté » = le detector a déclenché une remédiation (nouvel incident
    enregistré) — c'est l'action autonome de l'IA, pas un simple clignotement
    d'affichage. On observe pendant la charge ET après (la fenêtre de 30 s met
    du temps à refléter une attaque courte).
    """
    print(f"\n=== {sc['nom']} ===", flush=True)
    print("  (réinitialisation de l'état…)", flush=True)
    reset_state()
    print("  (stabilisation en cours…)", flush=True)
    wait_until_calm()
    base_incidents = incident_count()

    # Charge en arrière-plan.
    load = threading.Thread(
        target=generate_load,
        args=(sc["workers"], sc["duree"], sc.get("delai", 0.0), sc.get("ramp", False)),
        daemon=True,
    )
    load.start()
    load.join()  # attendre la fin de la charge
    load_end = time.time()

    # Fenêtre d'observation après la charge : on guette une remédiation
    # (le detector agit dans les ~30 s qui suivent) et le retour au calme.
    detected = False
    recovered = False
    rto = None
    deadline = load_end + 50
    while time.time() < deadline:
        if incident_count() > base_incidents:
            detected = True
        v = state().get("verdict")
        if detected and v in ("nominal", "idle"):
            recovered = True
            rto = round(time.time() - load_end, 1)
            break
        # Cas de contrôle : si rien n'est détecté et que c'est calme, on arrête vite.
        if not sc["attendu_incident"] and v in ("nominal", "idle") and time.time() - load_end > 35:
            recovered = True
            break
        time.sleep(2)

    attendu = sc["attendu_incident"]
    ok = (detected and recovered) if attendu else (not detected)
    print(f"  détecté={detected} reprise={recovered} "
          f"-> {'OK' if ok else 'ÉCHEC'}", flush=True)

    return {
        "nom": sc["nom"],
        "profil": sc["profil"],
        "attendu": "incident" if attendu else "aucun",
        "detecte": "oui" if detected else "non",
        "reprise": "oui" if recovered else ("n/a" if not attendu else "non"),
        "rto_s": rto if attendu and recovered else "—",
        "verdict": "OK" if ok else "ÉCHEC",
    }


SCENARIOS = [
    {"nom": "Flood volumétrique (DDoS)", "profil": "120 workers, 18 s",
     "workers": 120, "duree": 18, "attendu_incident": True},
    {"nom": "Burst intense (court)", "profil": "160 workers, 15 s",
     "workers": 160, "duree": 15, "attendu_incident": True},
    {"nom": "Montée progressive puis maintien", "profil": "ramp 8 s -> 140 workers, maintien 16 s",
     "workers": 140, "duree": 24, "ramp": True, "attendu_incident": True},
    {"nom": "Pression modérée soutenue", "profil": "85 workers, 16 s",
     "workers": 85, "duree": 16, "attendu_incident": True},
    {"nom": "Charge légitime élevée (contrôle)", "profil": "15 workers espacés, 14 s",
     "workers": 15, "duree": 14, "delai": 0.08, "attendu_incident": False},
    {"nom": "Sonde discrète (contrôle)", "profil": "3 workers espacés, 10 s",
     "workers": 3, "duree": 10, "delai": 0.2, "attendu_incident": False},
]


def ecrire_rapport(resultats, chemin):
    lignes = [
        "# Campagne de tests de résilience — RESILIENCE-ALPHA\n",
        "Chaque scénario est rejoué contre la plateforme ; le système doit "
        "détecter et se rétablir sur les attaques, et NE PAS réagir sur une "
        "charge légitime (cas de contrôle).\n",
        "| Scénario | Profil | Attendu | Détecté | Reprise | RTO (s) | Verdict |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for r in resultats:
        lignes.append(f"| {r['nom']} | {r['profil']} | {r['attendu']} | "
                      f"{r['detecte']} | {r['reprise']} | {r['rto_s']} | {r['verdict']} |")
    reussis = sum(1 for r in resultats if r["verdict"] == "OK")
    lignes.append(f"\n**Résultat global : {reussis}/{len(resultats)} scénarios conformes.**")
    with open(chemin, "w", encoding="utf-8") as f:
        f.write("\n".join(lignes) + "\n")
    print(f"\nRapport écrit : {chemin}", flush=True)


def main():
    global TARGET
    p = argparse.ArgumentParser()
    p.add_argument("--target", default=TARGET)
    p.add_argument("--rapport", default="docs/campagne-resilience.md")
    args = p.parse_args()
    TARGET = args.target

    print("Campagne de tests de résilience — démarrage")
    print("Assure-toi qu'AUCUNE autre attaque ne tourne (console/ddos).")
    resultats = [run_scenario(sc) for sc in SCENARIOS]

    print("\n================ RÉSULTATS ================")
    for r in resultats:
        print(f"  {r['verdict']:7} | {r['nom']}")
    reussis = sum(1 for r in resultats if r["verdict"] == "OK")
    print(f"\n{reussis}/{len(resultats)} scénarios conformes.")

    import os
    os.makedirs(os.path.dirname(args.rapport) or ".", exist_ok=True)
    ecrire_rapport(resultats, args.rapport)
    unblock_all()


if __name__ == "__main__":
    main()
