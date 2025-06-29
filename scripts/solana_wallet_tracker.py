import argparse
import json
import urllib.request
from typing import Set

RPC_URL = "https://api.mainnet-beta.solana.com"


def rpc_call(method: str, params):
    payload = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode()
    req = urllib.request.Request(RPC_URL, data=payload, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req) as resp:
        return json.load(resp)["result"]


def fetch_signatures(address: str, limit: int = 20):
    return rpc_call("getSignaturesForAddress", [address, {"limit": limit}])


def fetch_transaction(signature: str):
    return rpc_call("getTransaction", [signature, {"encoding": "jsonParsed"}])


def track_wallet(address: str, depth: int, visited: Set[str]):
    if depth <= 0 or address in visited:
        return
    visited.add(address)
    try:
        signatures = fetch_signatures(address)
    except Exception as exc:
        print(f"Failed to fetch signatures for {address}: {exc}")
        return
    for entry in signatures:
        sig = entry.get("signature")
        if not sig:
            continue
        try:
            tx = fetch_transaction(sig)
        except Exception as exc:
            print(f"Failed to fetch tx {sig}: {exc}")
            continue
        if not tx:
            continue
        message = tx["transaction"]["message"]
        instructions = message.get("instructions", [])
        for ix in instructions:
            parsed = ix.get("parsed")
            if parsed and parsed.get("type") == "transfer":
                info = parsed.get("info", {})
                src = info.get("source")
                dst = info.get("destination")
                lamports = info.get("lamports")
                if src == address and dst:
                    print(f"{src} -> {dst}: {lamports} lamports (tx: {sig})")
                    track_wallet(dst, depth - 1, visited)


def main():
    parser = argparse.ArgumentParser(description="Track SOL transfers across wallets")
    parser.add_argument("address", help="Starting wallet address")
    parser.add_argument("-d", "--depth", type=int, default=2, help="Recursion depth")
    parser.add_argument("-l", "--limit", type=int, default=20, help="Number of signatures to fetch per wallet")
    args = parser.parse_args()

    global fetch_signatures
    def fetch_signatures(address: str, limit: int = args.limit):
        return rpc_call("getSignaturesForAddress", [address, {"limit": limit}])

    track_wallet(args.address, args.depth, set())


if __name__ == "__main__":
    main()

