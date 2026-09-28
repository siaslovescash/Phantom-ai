import asyncio
import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Optional
# ============================================================
# SUPPORTED CHAINS
# ============================================================
SOLANA_CHAIN = "solana"
ROBINHOOD_CHAIN = "robinhood"
ROBINHOOD_CHAIN_ID = 4663
ROBINHOOD_RPC = (
    "https://rpc.mainnet.chain.robinhood.com"
)
# ============================================================
# RISK LIMITS
# ============================================================
MIN_LIQUIDITY_USD = 25_000
MIN_VOLUME_24H_USD = 10_000
MAX_TOP_HOLDER_PERCENT = 20.0
# ============================================================
# DATA SOURCES
# ============================================================
DEXSCREENER_TOKEN_URL = (
    "https://api.dexscreener.com/latest/dex/tokens/"
)
RUGCHECK_URL = (
    "https://api.rugcheck.xyz/v1/tokens/"
)
# ============================================================
# RISK REPORT
# ============================================================
@dataclass
class RiskReport:
    token_address: str
    chain: str
    risk_score: int
    risk_level: str
    decision: str
    liquidity: float
    volume_24h: float
    market_cap: float
    price: float
    reasons: list[str]
    mint_authority: Optional[str] = None
    freeze_authority: Optional[str] = None
    top_holder_percent: Optional[float] = None
    token_name: str = "Unknown"
    token_symbol: str = "UNKNOWN"
# ============================================================
# HTTP HELPERS
# ============================================================
def fetch_json(
    url: str,
    method: str = "GET",
    payload: Optional[dict] = None,
    timeout: int = 15
) -> Any:
    headers = {
        "User-Agent": "Phantom-AI-Trader/1.0",
        "Accept": "application/json",
    }
    data = None
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = (
            "application/json"
        )
    request = urllib.request.Request(
        url,
        data=data,
        headers=headers,
        method=method
    )
    with urllib.request.urlopen(
        request,
        timeout=timeout
    ) as response:
        raw = response.read().decode("utf-8")
        return json.loads(raw)
# ============================================================
# ADDRESS DETECTION
# ============================================================
def looks_like_solana_address(
    token_address: str
) -> bool:
    address = token_address.strip()
    if len(address) < 32 or len(address) > 44:
        return False
    # Solana addresses are base58 and do not use 0x.
    if address.lower().startswith("0x"):
        return False
    base58_chars = (
        "123456789ABCDEFGHJKLMNPQRSTUVWXYZ"
        "abcdefghijkmnopqrstuvwxyz"
    )
    return all(
        character in base58_chars
        for character in address
    )
def looks_like_evm_address(
    token_address: str
) -> bool:
    address = token_address.strip()
    if not address.startswith("0x"):
        return False
    if len(address) != 42:
        return False
    hex_chars = "0123456789abcdefABCDEF"
    return all(
        character in hex_chars
        for character in address[2:]
    )
# ============================================================
# CHAIN DETECTION
# ============================================================
def detect_chain(
    token_address: str
) -> Optional[str]:
    address = token_address.strip()
    if looks_like_solana_address(address):
        return SOLANA_CHAIN
    if looks_like_evm_address(address):
        return ROBINHOOD_CHAIN
    return None
# ============================================================
# DEXSCREENER
# ============================================================
def get_dexscreener_data(
    token_address: str
) -> dict:
    url = (
        DEXSCREENER_TOKEN_URL
        + token_address
    )
    try:
        data = fetch_json(url)
        if not isinstance(data, dict):
            return {}
        return data
    except Exception as error:
        print(
            f"DEXSCREENER ERROR | "
            f"TOKEN={token_address} | "
            f"ERROR={error}",
            flush=True
        )
        return {}
# ============================================================
# SELECT SUPPORTED DEXSCREENER PAIR
# ============================================================
def select_pair(
    data: dict,
    chain: str
) -> Optional[dict]:
    pairs = data.get("pairs", [])
    if not isinstance(pairs, list):
        return None
    matching_pairs = []
    for pair in pairs:
        if not isinstance(pair, dict):
            continue
        pair_chain = str(
            pair.get("chainId", "")
        ).lower()
        if chain == SOLANA_CHAIN:
            if pair_chain == "solana":
                matching_pairs.append(pair)
        elif chain == ROBINHOOD_CHAIN:
            if pair_chain in (
                "robinhood",
                "robinhood-chain",
                "robinhoodchain"
            ):
                matching_pairs.append(pair)
    if not matching_pairs:
        return None
    matching_pairs.sort(
        key=lambda item: float(
            item.get(
                "liquidity",
                {}
            ).get(
                "usd",
                0
            ) or 0
        ),
        reverse=True
    )
    return matching_pairs[0]
# ============================================================
# SOLANA RUGCHECK
# ============================================================
def get_rugcheck_data(
    token_address: str
) -> dict:
    url = (
        RUGCHECK_URL
        + token_address
        + "/report/summary"
    )
    try:
        data = fetch_json(url)
        if isinstance(data, dict):
            return data
    except Exception as error:
        print(
            f"RUGCHECK ERROR | "
            f"TOKEN={token_address} | "
            f"ERROR={error}",
            flush=True
        )
    return {}
# ============================================================
# ROBINHOOD CHAIN RPC
# ============================================================
def robinhood_rpc_call(
    method: str,
    params: list
) -> Any:
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": method,
        "params": params
    }
    try:
        result = fetch_json(
            ROBINHOOD_RPC,
            method="POST",
            payload=payload
        )
        if isinstance(result, dict):
            if "error" in result:
                print(
                    f"ROBINHOOD RPC ERROR | "
                    f"METHOD={method} | "
                    f"ERROR={result['error']}",
                    flush=True
                )
                return None
            return result.get("result")
    except Exception as error:
        print(
            f"ROBINHOOD RPC REQUEST ERROR | "
            f"METHOD={method} | "
            f"ERROR={error}",
            flush=True
        )
    return None
# ============================================================
# ROBINHOOD TOKEN METADATA
# ============================================================
def get_robinhood_token_metadata(
    token_address: str
) -> dict:
    metadata = {
        "name": "Unknown",
        "symbol": "UNKNOWN",
        "decimals": None,
        "total_supply": None,
    }
    # --------------------------------------------------------
    # ERC-20 name()
    # --------------------------------------------------------
    name_data = robinhood_rpc_call(
        "eth_call",
        [
            {
                "to": token_address,
                "data": "0x06fdde03"
            },
            "latest"
        ]
    )
    if name_data:
        try:
            metadata["name"] = decode_abi_string(
                name_data
            )
        except Exception:
            pass
    # --------------------------------------------------------
    # ERC-20 symbol()
    # --------------------------------------------------------
    symbol_data = robinhood_rpc_call(
        "eth_call",
        [
            {
                "to": token_address,
                "data": "0x95d89b41"
            },
            "latest"
        ]
    )
    if symbol_data:
        try:
            metadata["symbol"] = decode_abi_string(
                symbol_data
            )
        except Exception:
            pass
    # --------------------------------------------------------
    # ERC-20 decimals()
    # --------------------------------------------------------
    decimals_data = robinhood_rpc_call(
        "eth_call",
        [
            {
                "to": token_address,
                "data": "0x313ce567"
            },
            "latest"
        ]
    )
    if decimals_data:
        try:
            metadata["decimals"] = int(
                decimals_data,
                16
            )
        except Exception:
            pass
    # --------------------------------------------------------
    # ERC-20 totalSupply()
    # --------------------------------------------------------
    supply_data = robinhood_rpc_call(
        "eth_call",
        [
            {
                "to": token_address,
                "data": "0x18160ddd"
            },
            "latest"
        ]
    )
    if supply_data:
        try:
            metadata["total_supply"] = int(
                supply_data,
                16
            )
        except Exception:
            pass
    return metadata
# ============================================================
# ABI STRING DECODER
# ============================================================
def decode_abi_string(
    data: str
) -> str:
    if not data:
        return ""
    raw = data[2:] if data.startswith("0x") else data
    # Standard ABI dynamic string.
    if len(raw) >= 128:
        try:
            offset = int(
                raw[0:64],
                16
            )
            length_position = offset * 2
            length = int(
                raw[
                    length_position:
                    length_position + 64
                ],
                16
            )
            start = (
                length_position
                + 64
            )
            end = start + (length * 2)
            value = bytes.fromhex(
                raw[start:end]
            ).decode(
                "utf-8",
                errors="ignore"
            )
            if value:
                return value.strip()
        except Exception:
            pass
    # Some contracts return bytes32.
    try:
        value = bytes.fromhex(
            raw[-64:]
        ).decode(
            "utf-8",
            errors="ignore"
        ).rstrip("\x00")
        return value.strip()
    except Exception:
        return ""
# ============================================================
# BASIC TOKEN CONTRACT CHECK
# ============================================================
def check_robinhood_contract(
    token_address: str
) -> list[str]:
    reasons = []
    code = robinhood_rpc_call(
        "eth_getCode",
        [
            token_address,
            "latest"
        ]
    )
    if code is None:
        reasons.append(
            "Could not verify Robinhood Chain contract."
        )
        return reasons
    if code in ("0x", "0x0", ""):
        reasons.append(
            "Address does not appear to contain a smart contract."
        )
    return reasons
# ============================================================
# NUMERIC HELPERS
# ============================================================
def safe_float(
    value: Any,
    default: float = 0.0
) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except Exception:
        return default
# ============================================================
# RISK SCORE
# ============================================================
def calculate_risk_score(
    liquidity: float,
    volume_24h: float,
    mint_authority: Optional[str],
    freeze_authority: Optional[str],
    top_holder_percent: Optional[float],
    hard_failures: list[str],
    chain: str
) -> tuple[int, str, str]:
    score = 100
    reasons = []
    # --------------------------------------------------------
    # Liquidity
    # --------------------------------------------------------
    if liquidity < MIN_LIQUIDITY_USD:
        score -= 35
        reasons.append(
            "Liquidity is below the minimum threshold."
        )
    elif liquidity < 100_000:
        score -= 10
        reasons.append(
            "Liquidity is relatively low."
        )
    # --------------------------------------------------------
    # Volume
    # --------------------------------------------------------
    if volume_24h < MIN_VOLUME_24H_USD:
        score -= 20
        reasons.append(
            "24h trading volume is below the minimum threshold."
        )
    elif volume_24h < 50_000:
        score -= 5
        reasons.append(
            "24h trading volume is relatively low."
        )
    # --------------------------------------------------------
    # Solana authorities
    # --------------------------------------------------------
    if chain == SOLANA_CHAIN:
        if mint_authority:
            score -= 25
            reasons.append(
                "Mint authority is still present."
            )
        if freeze_authority:
            score -= 25
            reasons.append(
                "Freeze authority is still present."
            )
        if (
            top_holder_percent is not None
            and top_holder_percent
            > MAX_TOP_HOLDER_PERCENT
        ):
            score -= 20
            reasons.append(
                "Top holder concentration is above 20%."
            )
    # --------------------------------------------------------
    # Hard failures
    # --------------------------------------------------------
    if hard_failures:
        score -= 30
        reasons.extend(
            hard_failures
        )
    score = max(
        0,
        min(
            100,
            score
        )
    )
    # --------------------------------------------------------
    # Risk levels
    # --------------------------------------------------------
    if score >= 80:
        risk_level = "LOW"
    elif score >= 60:
        risk_level = "MEDIUM"
    elif score >= 40:
        risk_level = "HIGH"
    else:
        risk_level = "EXTREME"
    # --------------------------------------------------------
    # Trading decision
    # --------------------------------------------------------
    if hard_failures:
        decision = "NO-TRADE"
    elif score >= 80:
        decision = "BUY-CANDIDATE"
    elif score >= 60:
        decision = "WAIT"
    else:
        decision = "NO-TRADE"
    return (
        score,
        risk_level,
        decision
    )
# ============================================================
# SOLANA ANALYSIS
# ============================================================
def analyze_solana(
    token_address: str
) -> RiskReport:
    reasons = []
    hard_failures = []
    dex_data = get_dexscreener_data(
        token_address
    )
    pair = select_pair(
        dex_data,
        SOLANA_CHAIN
    )
    if not pair:
        return RiskReport(
            token_address=token_address,
            chain=SOLANA_CHAIN,
            risk_score=0,
            risk_level="UNKNOWN",
            decision="NO-TRADE",
            liquidity=0,
            volume_24h=0,
            market_cap=0,
            price=0,
            reasons=[
                "No supported Solana trading pair was found."
            ]
        )
    liquidity = safe_float(
        pair.get(
            "liquidity",
            {}
        ).get(
            "usd"
        )
    )
    volume_24h = safe_float(
        pair.get(
            "volume",
            {}
        ).get(
            "h24"
        )
    )
    market_cap = safe_float(
        pair.get(
            "marketCap"
        )
    )
    price = safe_float(
        pair.get(
            "priceUsd"
        )
    )
    base_token = pair.get(
        "baseToken",
        {}
    )
    token_name = base_token.get(
        "name",
        "Unknown"
    )
    token_symbol = base_token.get(
        "symbol",
        "UNKNOWN"
    )
    rug_data = get_rugcheck_data(
        token_address
    )
    mint_authority = None
    freeze_authority = None
    top_holder_percent = None
    # --------------------------------------------------------
    # RugCheck fields
    # --------------------------------------------------------
    mint_authority = rug_data.get(
        "mintAuthority"
    )
    freeze_authority = rug_data.get(
        "freezeAuthority"
    )
    # Some RugCheck responses expose these
    # through token metadata.
    token_meta = rug_data.get(
        "tokenMeta",
        {}
    )
    if isinstance(token_meta, dict):
        if mint_authority is None:
            mint_authority = token_meta.get(
                "mintAuthority"
            )
        if freeze_authority is None:
            freeze_authority = token_meta.get(
                "freezeAuthority"
            )
    # --------------------------------------------------------
    # Holder concentration
    # --------------------------------------------------------
    top_holders = rug_data.get(
        "topHolders"
    )
    if isinstance(
        top_holders,
        list
    ) and top_holders:
        first_holder = top_holders[0]
        if isinstance(
            first_holder,
            dict
        ):
            percent = first_holder.get(
                "pct"
            )
            if percent is None:
                percent = first_holder.get(
                    "percentage"
                )
            top_holder_percent = safe_float(
                percent,
                None
            )
    # --------------------------------------------------------
    # Risk checks
    # --------------------------------------------------------
    if liquidity < MIN_LIQUIDITY_USD:
        hard_failures.append(
            "Liquidity is too low for the configured trading rules."
        )
    if volume_24h < MIN_VOLUME_24H_USD:
        hard_failures.append(
            "24h volume is too low for the configured trading rules."
        )
    if mint_authority:
        hard_failures.append(
            "Mint authority is active."
        )
    if freeze_authority:
        hard_failures.append(
            "Freeze authority is active."
        )
    if (
        top_holder_percent is not None
        and top_holder_percent
        > MAX_TOP_HOLDER_PERCENT
    ):
        hard_failures.append(
            "Top holder concentration exceeds 20%."
        )
    score, risk_level, decision = (
        calculate_risk_score(
            liquidity=liquidity,
            volume_24h=volume_24h,
            mint_authority=mint_authority,
            freeze_authority=freeze_authority,
            top_holder_percent=top_holder_percent,
            hard_failures=hard_failures,
            chain=SOLANA_CHAIN
        )
    )
    reasons.extend(
        hard_failures
    )
    if not reasons:
        reasons.append(
            "No configured high-risk conditions were detected."
        )
    return RiskReport(
        token_address=token_address,
        chain=SOLANA_CHAIN,
        risk_score=score,
        risk_level=risk_level,
        decision=decision,
        liquidity=liquidity,
        volume_24h=volume_24h,
        market_cap=market_cap,
        price=price,
        reasons=reasons,
        mint_authority=mint_authority,
        freeze_authority=freeze_authority,
        top_holder_percent=top_holder_percent,
        token_name=token_name,
        token_symbol=token_symbol
    )
# ============================================================
# ROBINHOOD CHAIN ANALYSIS
# ============================================================
def analyze_robinhood(
    token_address: str
) -> RiskReport:
    reasons = []
    hard_failures = []
    # --------------------------------------------------------
    # DexScreener
    # --------------------------------------------------------
    dex_data = get_dexscreener_data(
        token_address
    )
    pair = select_pair(
        dex_data,
        ROBINHOOD_CHAIN
    )
    liquidity = 0.0
    volume_24h = 0.0
    market_cap = 0.0
    price = 0.0
    token_name = "Unknown"
    token_symbol = "UNKNOWN"
    if pair:
        liquidity = safe_float(
            pair.get(
                "liquidity",
                {}
            ).get(
                "usd"
            )
        )
        volume_24h = safe_float(
            pair.get(
                "volume",
                {}
            ).get(
                "h24"
            )
        )
        market_cap = safe_float(
            pair.get(
                "marketCap"
            )
        )
        price = safe_float(
            pair.get(
                "priceUsd"
            )
        )
        base_token = pair.get(
            "baseToken",
            {}
        )
        token_name = base_token.get(
            "name",
            "Unknown"
        )
        token_symbol = base_token.get(
            "symbol",
            "UNKNOWN"
        )
    else:
        reasons.append(
            "No supported Robinhood Chain DEX pair was found."
        )
        hard_failures.append(
            "No verified market data was found."
        )
    # --------------------------------------------------------
    # Contract verification
    # --------------------------------------------------------
    contract_reasons = (
        check_robinhood_contract(
            token_address
        )
    )
    reasons.extend(
        contract_reasons
    )
    if contract_reasons:
        hard_failures.extend(
            contract_reasons
        )
    # --------------------------------------------------------
    # Token metadata
    # --------------------------------------------------------
    metadata = (
        get_robinhood_token_metadata(
            token_address
        )
    )
    if metadata.get("name") != "Unknown":
        token_name = metadata["name"]
    if metadata.get("symbol") != "UNKNOWN":
        token_symbol = metadata["symbol"]
    # --------------------------------------------------------
    # Market safety checks
    # --------------------------------------------------------
    if liquidity < MIN_LIQUIDITY_USD:
        hard_failures.append(
            "Liquidity is too low for the configured trading rules."
        )
    if volume_24h < MIN_VOLUME_24H_USD:
        hard_failures.append(
            "24h volume is too low for the configured trading rules."
        )
    # --------------------------------------------------------
    # IMPORTANT:
    # Robinhood Chain does not use RugCheck's Solana
    # authority model.
    #
    # We therefore do NOT pretend that Solana mint/freeze
    # checks apply here.
    # --------------------------------------------------------
    score, risk_level, decision = (
        calculate_risk_score(
            liquidity=liquidity,
            volume_24h=volume_24h,
            mint_authority=None,
            freeze_authority=None,
            top_holder_percent=None,
            hard_failures=hard_failures,
            chain=ROBINHOOD_CHAIN
        )
    )
    if not reasons:
        reasons.append(
            "No configured high-risk conditions were detected."
        )
    return RiskReport(
        token_address=token_address,
        chain=ROBINHOOD_CHAIN,
        risk_score=score,
        risk_level=risk_level,
        decision=decision,
        liquidity=liquidity,
        volume_24h=volume_24h,
        market_cap=market_cap,
        price=price,
        reasons=list(dict.fromkeys(reasons)),
        token_name=token_name,
        token_symbol=token_symbol
    )
# ============================================================
# MAIN ANALYZER
# ============================================================
async def analyze_token(
    token_address: str
) -> RiskReport:
    token_address = token_address.strip()
    if not token_address:
        return RiskReport(
            token_address="",
            chain="unknown",
            risk_score=0,
            risk_level="UNKNOWN",
            decision="NO-TRADE",
            liquidity=0,
            volume_24h=0,
            market_cap=0,
            price=0,
            reasons=[
                "Token address was empty."
            ]
        )
    chain = detect_chain(
        token_address
    )
    print(
        f"RISK ENGINE | "
        f"TOKEN={token_address} | "
        f"DETECTED_CHAIN={chain}",
        flush=True
    )
    # --------------------------------------------------------
    # Unsupported address
    # --------------------------------------------------------
    if chain is None:
        return RiskReport(
            token_address=token_address,
            chain="unsupported",
            risk_score=0,
            risk_level="UNKNOWN",
            decision="NO-TRADE",
            liquidity=0,
            volume_24h=0,
            market_cap=0,
            price=0,
            reasons=[
                "Address is not recognized as a supported "
                "Solana or Robinhood Chain token address."
            ]
        )
    # --------------------------------------------------------
    # Solana
    # --------------------------------------------------------
    if chain == SOLANA_CHAIN:
        return await asyncio.to_thread(
            analyze_solana,
            token_address
        )
    # --------------------------------------------------------
    # Robinhood Chain
    # --------------------------------------------------------
    if chain == ROBINHOOD_CHAIN:
        return await asyncio.to_thread(
            analyze_robinhood,
            token_address
        )
    # Safety fallback
    return RiskReport(
        token_address=token_address,
        chain="unknown",
        risk_score=0,
        risk_level="UNKNOWN",
        decision="NO-TRADE",
        liquidity=0,
        volume_24h=0,
        market_cap=0,
        price=0,
        reasons=[
            "Unsupported blockchain."
        ]
    )
