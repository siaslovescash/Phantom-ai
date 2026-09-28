import asyncio
import json
import urllib.request
from datetime import datetime, timezone
# ============================================================
# PHANTOM AI TOKEN SCANNER
# Supported chains:
#   1. Solana
#   2. Robinhood Chain
#
# This file ONLY discovers and analyzes tokens.
# It does NOT execute trades.
# ============================================================
DEXSCREENER_LATEST_PROFILES = (
    "https://api.dexscreener.com/token-profiles/latest/v1"
)
DEXSCREENER_TOKEN_PAIRS = (
    "https://api.dexscreener.com/latest/dex/tokens/"
)
SUPPORTED_CHAINS = {
    "solana",
    "robinhood",
}
# ============================================================
# HTTP
# ============================================================
def fetch_json(url, timeout=15):
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Phantom-AI-Trader/1.0",
            "Accept": "application/json",
        },
    )
    with urllib.request.urlopen(
        request,
        timeout=timeout
    ) as response:
        return json.loads(
            response.read().decode("utf-8")
        )
# ============================================================
# LATEST TOKEN PROFILES
# ============================================================
def get_latest_profiles():
    try:
        data = fetch_json(
            DEXSCREENER_LATEST_PROFILES
        )
        if isinstance(data, list):
            return data
        return []
    except Exception as error:
        print(
            f"SCANNER PROFILE ERROR | {error}",
            flush=True
        )
        return []
# ============================================================
# TOKEN PAIRS
# ============================================================
def get_token_pairs(token_address):
    try:
        data = fetch_json(
            DEXSCREENER_TOKEN_PAIRS
            + token_address
        )
        if isinstance(data, dict):
            pairs = data.get(
                "pairs",
                []
            )
            if isinstance(pairs, list):
                return pairs
        return []
    except Exception as error:
        print(
            f"SCANNER PAIR ERROR | "
            f"TOKEN={token_address} | "
            f"ERROR={error}",
            flush=True
        )
        return []
# ============================================================
# CHAIN NORMALIZATION
# ============================================================
def normalize_chain(chain_id):
    if not chain_id:
        return None
    value = str(
        chain_id
    ).strip().lower()
    if value == "solana":
        return "solana"
    if value in (
        "robinhood",
        "robinhood-chain",
        "robinhoodchain",
    ):
        return "robinhood"
    return None
# ============================================================
# SELECT BEST PAIR
# ============================================================
def select_best_pair(
    pairs,
    chain
):
    matching = []
    for pair in pairs:
        if not isinstance(
            pair,
            dict
        ):
            continue
        detected_chain = normalize_chain(
            pair.get("chainId")
        )
        if detected_chain != chain:
            continue
        liquidity = (
            pair.get(
                "liquidity",
                {}
            ).get(
                "usd",
                0
            )
            or 0
        )
        try:
            liquidity = float(
                liquidity
            )
        except Exception:
            liquidity = 0
        matching.append(
            (
                liquidity,
                pair
            )
        )
    if not matching:
        return None
    matching.sort(
        key=lambda item: item[0],
        reverse=True
    )
    return matching[0][1]
# ============================================================
# TOKEN DATA
# ============================================================
def build_token_record(
    profile,
    pair,
    chain
):
    base_token = pair.get(
        "baseToken",
        {}
    )
    token_address = (
        base_token.get(
            "address"
        )
        or profile.get(
            "tokenAddress"
        )
    )
    name = (
        base_token.get(
            "name"
        )
        or profile.get(
            "name"
        )
        or "Unknown"
    )
    symbol = (
        base_token.get(
            "symbol"
        )
        or profile.get(
            "symbol"
        )
        or "UNKNOWN"
    )
    liquidity = (
        pair.get(
            "liquidity",
            {}
        ).get(
            "usd",
            0
        )
        or 0
    )
    volume_24h = (
        pair.get(
            "volume",
            {}
        ).get(
            "h24",
            0
        )
        or 0
    )
    market_cap = (
        pair.get(
            "marketCap",
            0
        )
        or 0
    )
    fdv = (
        pair.get(
            "fdv",
            0
        )
        or 0
    )
    price = (
        pair.get(
            "priceUsd",
            0
        )
        or 0
    )
    price_change_24h = (
        pair.get(
            "priceChange",
            {}
        ).get(
            "h24",
            0
        )
        or 0
    )
    pair_created_at = pair.get(
        "pairCreatedAt"
    )
    return {
        "chain": chain,
        "token_address": token_address,
        "name": name,
        "symbol": symbol,
        "liquidity_usd": safe_float(
            liquidity
        ),
        "volume_24h_usd": safe_float(
            volume_24h
        ),
        "market_cap": safe_float(
            market_cap
        ),
        "fdv": safe_float(
            fdv
        ),
        "price_usd": safe_float(
            price
        ),
        "price_change_24h": safe_float(
            price_change_24h
        ),
        "pair_created_at": pair_created_at,
        "dex": pair.get(
            "dexId",
            "unknown"
        ),
        "pair_url": pair.get(
            "url"
        ),
    }
# ============================================================
# SAFE FLOAT
# ============================================================
def safe_float(value):
    try:
        return float(
            value
        )
    except Exception:
        return 0.0
# ============================================================
# TOKEN AGE
# ============================================================
def calculate_token_age(
    pair_created_at
):
    if not pair_created_at:
        return None
    try:
        created_ms = int(
            pair_created_at
        )
        created = datetime.fromtimestamp(
            created_ms / 1000,
            tz=timezone.utc
        )
        now = datetime.now(
            timezone.utc
        )
        seconds = (
            now - created
        ).total_seconds()
        if seconds < 0:
            seconds = 0
        return int(
            seconds
        )
    except Exception:
        return None
# ============================================================
# FORMAT AGE
# ============================================================
def format_age(
    seconds
):
    if seconds is None:
        return "Unknown"
    if seconds < 60:
        return f"{seconds}s"
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes}m"
    hours = minutes // 60
    if hours < 24:
        return f"{hours}h"
    days = hours // 24
    return f"{days}d"
# ============================================================
# SCAN LATEST TOKENS
# ============================================================
def scan_latest_tokens(
    max_profiles=100
):
    print(
        "SCANNER STARTING",
        flush=True
    )
    profiles = get_latest_profiles()
    if not profiles:
        print(
            "SCANNER COMPLETE | "
            "NO PROFILES FOUND",
            flush=True
        )
        return []
    results = []
    seen = set()
    for profile in profiles[:max_profiles]:
        if not isinstance(
            profile,
            dict
        ):
            continue
        chain = normalize_chain(
            profile.get(
                "chainId"
            )
        )
        if chain not in SUPPORTED_CHAINS:
            continue
        token_address = (
            profile.get(
                "tokenAddress"
            )
        )
        if not token_address:
            continue
        key = (
            chain,
            token_address.lower()
        )
        if key in seen:
            continue
        seen.add(key)
        pairs = get_token_pairs(
            token_address
        )
        pair = select_best_pair(
            pairs,
            chain
        )
        if not pair:
            continue
        token = build_token_record(
            profile,
            pair,
            chain
        )
        token["age_seconds"] = (
            calculate_token_age(
                token[
                    "pair_created_at"
                ]
            )
        )
        token["age"] = format_age(
            token[
                "age_seconds"
            ]
        )
        results.append(
            token
        )
    print(
        f"SCANNER COMPLETE | "
        f"SUPPORTED RESULTS={len(results)}",
        flush=True
    )
    return results
# ============================================================
# FILTER CANDIDATES
# ============================================================
def filter_candidates(
    tokens,
    min_liquidity=25_000,
    min_volume=10_000,
    min_market_cap=1_000,
    max_market_cap=500_000
):
    candidates = []
    for token in tokens:
        liquidity = token.get(
            "liquidity_usd",
            0
        )
        volume = token.get(
            "volume_24h_usd",
            0
        )
        market_cap = token.get(
            "market_cap",
            0
        )
        if liquidity < min_liquidity:
            continue
        if volume < min_volume:
            continue
        if market_cap < min_market_cap:
            continue
        if market_cap > max_market_cap:
            continue
        candidates.append(
            token
        )
    candidates.sort(
        key=lambda item: (
            item.get(
                "volume_24h_usd",
                0
            ),
            item.get(
                "liquidity_usd",
                0
            )
        ),
        reverse=True
    )
    return candidates
# ============================================================
# ASYNC SCAN
# ============================================================
async def scan_tokens(
    max_profiles=100
):
    return await asyncio.to_thread(
        scan_latest_tokens,
        max_profiles
    )
# ============================================================
# ASYNC CANDIDATE SCAN
# ============================================================
async def scan_candidates(
    max_profiles=100
):
    tokens = await scan_tokens(
        max_profiles
    )
    candidates = filter_candidates(
        tokens
    )
    print(
        f"CANDIDATE SCAN COMPLETE | "
        f"RESULTS={len(candidates)}",
        flush=True
    )
    return candidates
# ============================================================
# CONVENIENCE FUNCTION
# ============================================================
async def get_new_candidates(
    max_profiles=100
):
    return await scan_candidates(
        max_profiles
    )
# ============================================================
# TEST MODE
# ============================================================
if __name__ == "__main__":
    print(
        "PHANTOM AI SCANNER TEST",
        flush=True
    )
    results = scan_latest_tokens(
        max_profiles=25
    )
    print(
        f"FOUND {len(results)} TOKENS",
        flush=True
    )
    for token in results[:10]:
        print(
            json.dumps(
                token,
                indent=2
            ),
            flush=True
        )
