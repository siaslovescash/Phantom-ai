import aiohttp
from dataclasses import dataclass, field
from typing import Optional


# ============================================================
# RISK ENGINE
# ============================================================
# This module analyzes a Solana token before the trading engine
# is allowed to consider entering a position.
#
# IMPORTANT:
# This is a safety/risk system, NOT a guarantee against rugs.
# ============================================================


@dataclass
class RiskReport:
    token_address: str

    risk_score: int = 0
    risk_level: str = "UNKNOWN"
    decision: str = "NO-TRADE"

    liquidity_usd: float = 0.0
    volume_24h_usd: float = 0.0
    market_cap_usd: float = 0.0

    mint_authority: Optional[str] = None
    freeze_authority: Optional[str] = None

    top_holder_percent: Optional[float] = None

    reasons: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


# ============================================================
# CONFIGURATION
# ============================================================

MIN_LIQUIDITY_USD = 25_000
MIN_VOLUME_24H_USD = 10_000

MAX_TOP_HOLDER_PERCENT = 20

# Risk score interpretation:
#
# 80-100 = relatively stronger setup
# 60-79  = caution
# 40-59  = high risk
# 0-39   = extreme risk
#
# The score does NOT mean the token is safe.
# ============================================================


# ============================================================
# FETCH RUGCHECK DATA
# ============================================================

async def fetch_rugcheck(token_address: str) -> dict:

    url = (
        "https://api.rugcheck.xyz/v1/tokens/"
        f"{token_address}/report/summary"
    )

    timeout = aiohttp.ClientTimeout(total=10)

    try:

        async with aiohttp.ClientSession(
            timeout=timeout
        ) as session:

            async with session.get(url) as response:

                if response.status != 200:
                    return {}

                return await response.json()

    except Exception:
        return {}


# ============================================================
# FETCH DEXSCREENER DATA
# ============================================================

async def fetch_market_data(token_address: str) -> dict:

    url = (
        "https://api.dexscreener.com/latest/dex/tokens/"
        f"{token_address}"
    )

    timeout = aiohttp.ClientTimeout(total=10)

    try:

        async with aiohttp.ClientSession(
            timeout=timeout
        ) as session:

            async with session.get(url) as response:

                if response.status != 200:
                    return {}

                return await response.json()

    except Exception:
        return {}


# ============================================================
# EXTRACT MARKET DATA
# ============================================================

def extract_market_data(data: dict) -> dict:

    pairs = data.get("pairs") or []

    solana_pairs = [
        pair
        for pair in pairs
        if pair.get("chainId") == "solana"
    ]

    if not solana_pairs:
        return {}

    pair = max(
        solana_pairs,
        key=lambda p: float(
            (p.get("liquidity") or {}).get("usd") or 0
        ),
    )

    liquidity = pair.get("liquidity") or {}
    volume = pair.get("volume") or {}

    return {
        "liquidity_usd": float(
            liquidity.get("usd") or 0
        ),

        "volume_24h_usd": float(
            volume.get("h24") or 0
        ),

        "market_cap_usd": float(
            pair.get("marketCap")
            or pair.get("fdv")
            or 0
        ),

        "price_usd": float(
            pair.get("priceUsd") or 0
        ),

        "pair": pair,
    }


# ============================================================
# RISK ANALYSIS
# ============================================================

async def analyze_token(
    token_address: str,
) -> RiskReport:

    report = RiskReport(
        token_address=token_address
    )

    score = 100

    # --------------------------------------------------------
    # GET DATA
    # --------------------------------------------------------

    rug_data = await fetch_rugcheck(
        token_address
    )

    market_data = await fetch_market_data(
        token_address
    )

    market = extract_market_data(
        market_data
    )

    # --------------------------------------------------------
    # MARKET DATA
    # --------------------------------------------------------

    if not market:

        report.risk_score = 0
        report.risk_level = "UNKNOWN"
        report.decision = "NO-TRADE"

        report.reasons.append(
            "Unable to obtain reliable market data."
        )

        return report

    report.liquidity_usd = market[
        "liquidity_usd"
    ]

    report.volume_24h_usd = market[
        "volume_24h_usd"
    ]

    report.market_cap_usd = market[
        "market_cap_usd"
    ]

    # --------------------------------------------------------
    # LIQUIDITY
    # --------------------------------------------------------

    if report.liquidity_usd <= 0:

        score -= 60

        report.reasons.append(
            "No usable liquidity detected."
        )

    elif report.liquidity_usd < MIN_LIQUIDITY_USD:

        score -= 35

        report.reasons.append(
            "Liquidity is below the minimum threshold."
        )

    elif report.liquidity_usd < MIN_LIQUIDITY_USD * 2:

        score -= 15

        report.warnings.append(
            "Liquidity is relatively thin."
        )

    # --------------------------------------------------------
    # VOLUME
    # --------------------------------------------------------

    if report.volume_24h_usd < MIN_VOLUME_24H_USD:

        score -= 20

        report.reasons.append(
            "24-hour trading volume is low."
        )

    # --------------------------------------------------------
    # RUGCHECK INFORMATION
    # --------------------------------------------------------

    if rug_data:

        # --------------------------------------------
        # MINT AUTHORITY
        # --------------------------------------------

        mint_authority = (
            rug_data.get("mintAuthority")
        )

        report.mint_authority = mint_authority

        if mint_authority:

            score -= 20

            report.reasons.append(
                "Mint authority appears to be active."
            )

        # --------------------------------------------
        # FREEZE AUTHORITY
        # --------------------------------------------

        freeze_authority = (
            rug_data.get("freezeAuthority")
        )

        report.freeze_authority = freeze_authority

        if freeze_authority:

            score -= 20

            report.reasons.append(
                "Freeze authority appears to be active."
            )

        # --------------------------------------------
        # TOP HOLDERS
        # --------------------------------------------

        top_holder_percent = (
            rug_data.get("topHolderPercent")
        )

        if top_holder_percent is not None:

            try:

                top_holder_percent = float(
                    top_holder_percent
                )

                report.top_holder_percent = (
                    top_holder_percent
                )

                if (
                    top_holder_percent
                    > MAX_TOP_HOLDER_PERCENT
                ):

                    score -= 30

                    report.reasons.append(
                        "Top holder concentration is high."
                    )

            except (TypeError, ValueError):

                pass

    else:

        report.warnings.append(
            "External token-risk data unavailable."
        )

    # --------------------------------------------------------
    # SCORE NORMALIZATION
    # --------------------------------------------------------

    score = max(
        0,
        min(100, score)
    )

    report.risk_score = score

    # --------------------------------------------------------
    # RISK LEVEL
    # --------------------------------------------------------

    if score >= 80:

        report.risk_level = "LOWER-RISK"

    elif score >= 60:

        report.risk_level = "CAUTION"

    elif score >= 40:

        report.risk_level = "HIGH-RISK"

    else:

        report.risk_level = "EXTREME-RISK"

    # --------------------------------------------------------
    # TRADE DECISION
    # --------------------------------------------------------

    #
    # We intentionally make the approval conservative.
    #

    if score >= 80:

        report.decision = "BUY-CANDIDATE"

    elif score >= 60:

        report.decision = "WAIT"

    else:

        report.decision = "NO-TRADE"

    # --------------------------------------------------------
    # FINAL HARD SAFETY RULES
    # --------------------------------------------------------

    if report.liquidity_usd < MIN_LIQUIDITY_USD:

        report.decision = "NO-TRADE"

        if (
            "Liquidity below hard minimum."
            not in report.reasons
        ):

            report.reasons.append(
                "Liquidity below hard minimum."
            )

    if report.volume_24h_usd < MIN_VOLUME_24H_USD:

        report.decision = "NO-TRADE"

    if (
        report.top_holder_percent is not None
        and report.top_holder_percent
        > MAX_TOP_HOLDER_PERCENT
    ):

        report.decision = "NO-TRADE"

    return report


# ============================================================
# SIMPLE TERMINAL TEST
# ============================================================

async def test_token(
    token_address: str
):

    report = await analyze_token(
        token_address
    )

    print()
    print("========================================")
    print("PHANTOM AI RISK REPORT")
    print("========================================")
    print(
        f"Token: {report.token_address}"
    )
    print(
        f"Risk Score: {report.risk_score}/100"
    )
    print(
        f"Risk Level: {report.risk_level}"
    )
    print(
        f"Decision: {report.decision}"
    )
    print(
        f"Liquidity: ${report.liquidity_usd:,.2f}"
    )
    print(
        f"24h Volume: ${report.volume_24h_usd:,.2f}"
    )

    if report.reasons:

        print()
        print("RISKS:")

        for reason in report.reasons:
            print(f"- {reason}")

    if report.warnings:

        print()
        print("WARNINGS:")

        for warning in report.warnings:
            print(f"- {warning}")

    print("========================================")
