import argparse
import asyncio
import json
import logging
import urllib.request
from collections import deque
from typing import Deque, Dict, List, Set, Tuple

RPC_URL = "https://api.mainnet-beta.solana.com"


async def rpc_call(method: str, params, semaphore: asyncio.Semaphore) -> dict:
    payload = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode()
    req = urllib.request.Request(RPC_URL, data=payload, headers={"Content-Type": "application/json"})
    loop = asyncio.get_running_loop()
    async with semaphore:
        return json.loads(await loop.run_in_executor(None, lambda: urllib.request.urlopen(req).read()))["result"]


async def fetch_signatures(address: str, limit: int, sem: asyncio.Semaphore):
    return await rpc_call("getSignaturesForAddress", [address, {"limit": limit}], sem)


async def fetch_transaction(signature: str, sem: asyncio.Semaphore):
    return await rpc_call("getTransaction", [signature, {"encoding": "jsonParsed"}], sem)


async def track_wallets(start: List[str], depth: int, limit: int, sem: asyncio.Semaphore) -> List[Dict[str, object]]:
    queue: Deque[Tuple[str, int]] = deque((addr, 0) for addr in start)
    visited: Set[str] = set()
    results: List[Dict[str, object]] = []

    while queue:
        address, lvl = queue.popleft()
        if address in visited or lvl >= depth:
            continue
        visited.add(address)
        try:
            signatures = await fetch_signatures(address, limit, sem)
        except Exception as exc:
            logging.warning("Failed to fetch signatures for %s: %s", address, exc)
            continue

        tx_tasks = [fetch_transaction(e.get("signature"), sem) for e in signatures if e.get("signature")]
        txs = await asyncio.gather(*tx_tasks, return_exceptions=True)

        for tx in txs:
            if isinstance(tx, Exception):
                logging.debug("Transaction fetch failed: %s", tx)
                continue
            if not tx:
                continue
            message = tx.get("transaction", {}).get("message", {})
            for ix in message.get("instructions", []):
                parsed = ix.get("parsed")
                if parsed and parsed.get("type") == "transfer":
                    info = parsed.get("info", {})
                    src = info.get("source")
                    dst = info.get("destination")
                    lamports = info.get("lamports")
                    if src == address and dst:
                        results.append({
                            "source": src,
                            "destination": dst,
                            "lamports": lamports,
                            "signature": tx.get("transaction", {}).get("signatures", [None])[0],
                            "level": lvl + 1,
                        })
                        queue.append((dst, lvl + 1))
    return results


def main():
    global RPC_URL

    parser = argparse.ArgumentParser(description="Track SOL transfers across wallets")
    parser.add_argument("addresses", nargs="*", help="Starting wallet addresses")
    parser.add_argument("-f", "--file", help="File containing wallet addresses")
    parser.add_argument("-d", "--depth", type=int, default=2, help="How many hops to follow")
    parser.add_argument("-l", "--limit", type=int, default=20, help="Signatures to fetch per wallet")
    parser.add_argument("-o", "--output", help="Write results to this JSON file")
    parser.add_argument("--api", default=RPC_URL, help="Solana RPC endpoint")
    parser.add_argument("-c", "--concurrency", type=int, default=4, help="Concurrent RPC calls")
    parser.add_argument("-v", "--verbose", action="store_true", help="Enable debug logging")
    args = parser.parse_args()

    addrs = list(args.addresses)
    if args.file:
        with open(args.file) as fh:
            for line in fh:
                line = line.strip()
                if line:
                    addrs.append(line)
    if not addrs:
        parser.error("No starting addresses provided")

    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO, format="%(levelname)s: %(message)s")

    RPC_URL = args.api

    async def runner():
        sem = asyncio.Semaphore(args.concurrency)
        results = await track_wallets(addrs, args.depth, args.limit, sem)
        if args.output:
            with open(args.output, "w") as out:
                json.dump(results, out, indent=2)
        else:
            print(json.dumps(results, indent=2))

    asyncio.run(runner())


if __name__ == "__main__":
    main()

