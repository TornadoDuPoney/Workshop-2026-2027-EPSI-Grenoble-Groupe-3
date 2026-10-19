"""
Génère un trafic de paiement NORMAL et régulier.
À lancer sur le PC Hôte pendant la récolte des métriques saines (mardi),
et aussi pendant la démo pour avoir un "avant" visible sur le dashboard.

Usage :
    pip install requests
    python trafic_normal.py --url http://localhost:8080/pay --rps 10
"""
import argparse
import threading
import time

import requests


def worker(url, delay, stop):
    while not stop.is_set():
        try:
            requests.post(url, params={"amount": 10}, timeout=3)
        except Exception:
            pass
        time.sleep(delay)


def main(url, rps):
    print(f"Trafic normal vers {url} à ~{rps} req/s (Ctrl+C pour arrêter)")
    stop = threading.Event()
    threads = [
        threading.Thread(target=worker, args=(url, 1.0, stop), daemon=True)
        for _ in range(rps)
    ]
    for t in threads:
        t.start()
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        stop.set()
        print("\nArrêt du trafic normal.")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--url", default="http://localhost:8080/pay")
    p.add_argument("--rps", type=int, default=10)
    args = p.parse_args()
    main(args.url, args.rps)
