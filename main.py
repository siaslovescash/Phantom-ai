import os
import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Optional

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands, tasks


# ============================================================
# CONFIGURATION
# ============================================================

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")

# SAFETY: real trading stays OFF until we deliberately enable it.
LIVE_TRADING = os.getenv("LIVE_TRADING", "false").lower() == "true"

# Paper-trading starting balance
PAPER_BALANCE_USD = float(os.getenv("PAPER_BALANCE_USD", "1000"))

# Maximum percentage of paper/live balance allowed in one position
MAX_POSITION_PERCENT = float(os.getenv("MAX_POSITION_PERCENT", "5"))

# Maximum loss allowed before the position is automatically closed
STOP_LOSS_PERCENT = float(os.getenv("STOP_LOSS_PERCENT", "12"))

# Take-profit level
TAKE_PROFIT_PERCENT = float(os.getenv("TAKE_PROFIT_PERCENT", "30"))

# Trailing stop after a position becomes profitable
TRAILING_STOP_PERCENT = float(os.getenv("TRAILING_STOP_PERCENT", "10"))

# Minimum liquidity required before considering a token
MIN_LIQUIDITY_USD = float(os.getenv("MIN_LIQUIDITY_USD", "25000"))

# Minimum 24h volume
MIN_VOLUME_USD = float(os.getenv("MIN_VOLUME_USD", "10000"))

# Minimum token age in seconds.
# Keeping this above zero prevents blindly buying brand-new pools.
MIN_TOKEN_AGE_SECONDS = int(os.getenv("MIN_TOKEN_AGE_SECONDS", "300"))

# Discord command cooldown
ANALYZE_COOLDOWN_SECONDS = 5


# ============================================================
# LOGGING
# ============================================================

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s | %(message)s",
)

logger = logging.getLogger("phantom-ai-trader")


# ============================================================
# DATA STRUCTURES
# ============================================================

@dataclass
class TokenAnalysis:
    address: str
    symbol: str = "UNKNOWN"
    name: str = "Unknown"

    price_usd: float = 0.0
    market_cap: float = 0.0
    liquidity_usd: float = 0.0
    volume_24h: float = 0.0

    price_change_5m: float = 0.0
    price_change_1h: float = 0.0
    price_change_24h: float = 0.0

    buys_5m: int = 0
    sells_5m: int = 0

    pair_age_seconds: Optional[float] = None

    risk_score: int = 100
    decision: str = "NO-TRADE"

    reasons: list[str] = field(default_factory=list)


@dataclass
class Position:
    token_address: str
    symbol: str

    entry_price: float
    quantity: float
    invested_usd: float

    highest_price: float
    opened_at: float = field(default_factory=time.time)

    realized_pnl: float = 0.0


# ============================================================
# PAPER TRADING PORTFOLIO
# ============================================================

class PaperPortfolio:

    def __init__(self):
        self.starting_balance = PAPER_BALANCE_USD
        self.cash = PAPER_BALANCE_USD
        self.positions: dict[str, Position] = {}

    def position_value(self, prices: dict[str, float]) -> float:
        total = 0.0

        for address, position in self.positions.items():
            price = prices.get(address, position.entry_price)
            total += position.quantity * price

        return total

    def total_equity(self, prices: dict[str, float]) -> float:
        return self.cash + self.position_value(prices)

    def buy(
        self,
        analysis: TokenAnalysis,
        amount_usd: float,
    ) -> tuple[bool, str]:

        if analysis.price_usd <= 0:
            return False, "Invalid token price."

        if amount_usd <= 0:
            return False, "Invalid amount."

        if amount_usd > self.cash:
            return False, "Insufficient paper balance."

        if analysis.address in self.positions:
            return False, "Position already exists."

        quantity = amount_usd / analysis.price_usd

        self.cash -= amount_usd

        self.positions[analysis.address] = Position(
            token_address=analysis.address,
            symbol=analysis.symbol,
            entry_price=analysis.price_usd,
            quantity=quantity,
            invested_usd=amount_usd,
            highest_price=analysis.price_usd,
        )

        return True, (
            f"Paper BUY {analysis.symbol} | "
            f"${amount_usd:,.2f} | "
            f"Entry ${analysis.price_usd:.10f}"
        )

    def sell(
        self,
        analysis: TokenAnalysis,
        reason: str,
    ) -> tuple[bool, str]:

        position = self.positions.get(analysis.address)

        if not position:
            return False, "No position exists."

        exit_value = position.quantity * analysis.price_usd
        pnl = exit_value - position.invested_usd

        self.cash += exit_value

        del self.positions[analysis.address]

        return True, (
            f"Paper SELL {analysis.symbol} | "
            f"Value ${exit_value:,.2f} | "
            f"PnL ${pnl:,.2f} | "
            f"Reason: {reason}"
        )


portfolio = PaperPortfolio()


# ============================================================
# MARKET DATA
# ============================================================

DEXSCREENER_URL = "https://api.dexscreener.com/latest/dex/tokens/{}"


async def fetch_token(address: str) -> Optional[TokenAnalysis]:

    url = DEXSCREENER_URL.format(address)

    timeout = aiohttp.ClientTimeout(total=10)

    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:

            async with session.get(
                url,
                headers={
                    "User-Agent": "Phantom-AI-Trader/1.0"
                },
            ) as response:

                if response.status != 200:
                    logger.warning(
                        "DexScreener returned HTTP %s",
                        response.status,
                    )
                    return None

                data = await response.json()

    except Exception as exc:
        logger.error("Market data error: %s", exc)
        return None

    pairs = data.get("pairs") or []

    # We currently focus on Solana.
    solana_pairs = [
        pair
        for pair in pairs
        if pair.get("chainId") == "solana"
    ]

    if not solana_pairs:
        return None

    # Choose the pair with the greatest liquidity.
    pair = max(
        solana_pairs,
        key=lambda p: float(
            (p.get("liquidity") or {}).get("usd") or 0
        ),
    )

    base = pair.get("baseToken") or {}
    txns = pair.get("txns") or {}
    volume = pair.get("volume") or {}
    liquidity = pair.get("liquidity") or {}
    price_change = pair.get("priceChange") or {}

    price = float(pair.get("priceUsd") or 0)

    liquidity_usd = float(liquidity.get("usd") or 0)
    volume_24h = float(volume.get("h24") or 0)

    market_cap = float(
        pair.get("marketCap")
        or pair.get("fdv")
        or 0
    )

    buys_5m = int(
        (txns.get("m5") or {}).get("buys") or 0
    )

    sells_5m = int(
        (txns.get("m5") or {}).get("sells") or 0
    )

    pair_created = pair.get("pairCreatedAt")

    pair_age_seconds = None

    if pair_created:
        pair_age_seconds = max(
            0,
            time.time() - (pair_created / 1000),
        )

    return TokenAnalysis(
        address=address,
        symbol=base.get("symbol") or "UNKNOWN",
        name=base.get("name") or "Unknown",
        price_usd=price,
        market_cap=market_cap,
        liquidity_usd=liquidity_usd,
        volume_24h=volume_24h,
        price_change_5m=float(price_change.get("m5") or 0),
        price_change_1h=float(price_change.get("h1") or 0),
        price_change_24h=float(price_change.get("h24") or 0),
        buys_5m=buys_5m,
        sells_5m=sells_5m,
        pair_age_seconds=pair_age_seconds,
    )


# ============================================================
# RISK / DECISION ENGINE
# ============================================================

def analyze_risk(analysis: TokenAnalysis) -> TokenAnalysis:

    score = 100
    reasons = []

    # --------------------------------------------------------
    # LIQUIDITY
    # --------------------------------------------------------

    if analysis.liquidity_usd < MIN_LIQUIDITY_USD:
        score -= 40
        reasons.append(
            "Liquidity below minimum threshold"
        )

    elif analysis.liquidity_usd < MIN_LIQUIDITY_USD * 2:
        score -= 15
        reasons.append(
            "Liquidity is relatively thin"
        )

    # --------------------------------------------------------
    # VOLUME
    # --------------------------------------------------------

    if analysis.volume_24h < MIN_VOLUME_USD:
        score -= 20
        reasons.append(
            "24h volume is too low"
        )

    # --------------------------------------------------------
    # TOKEN AGE
    # --------------------------------------------------------

    if analysis.pair_age_seconds is not None:

        if analysis.pair_age_seconds < MIN_TOKEN_AGE_SECONDS:
            score -= 30
            reasons.append(
                "Trading pair is extremely new"
            )

    # --------------------------------------------------------
    # BUY/SELL BALANCE
    # --------------------------------------------------------

    total_trades = (
        analysis.buys_5m +
        analysis.sells_5m
    )

    if total_trades > 0:

        sell_ratio = (
            analysis.sells_5m /
            total_trades
        )

        if sell_ratio > 0.75:
            score -= 35
            reasons.append(
                "Heavy selling pressure"
            )

        elif sell_ratio > 0.60:
            score -= 15
            reasons.append(
                "Elevated selling pressure"
            )

    # --------------------------------------------------------
    # PRICE BEHAVIOR
    # --------------------------------------------------------

    if analysis.price_change_5m < -15:
        score -= 30
        reasons.append(
            "Sharp 5-minute price decline"
        )

    elif analysis.price_change_5m < -8:
        score -= 15
        reasons.append(
            "Significant short-term decline"
        )

    # --------------------------------------------------------
    # EXTREME PUMP PROTECTION
    # --------------------------------------------------------

    if analysis.price_change_5m > 80:
        score -= 25
        reasons.append(
            "Extreme short-term price spike"
        )

    elif analysis.price_change_5m > 40:
        score -= 10
        reasons.append(
            "Large short-term price spike"
        )

    # --------------------------------------------------------
    # FINAL SCORE
    # --------------------------------------------------------

    score = max(0, min(100, score))

    analysis.risk_score = score
    analysis.reasons = reasons

    # Decision thresholds
    #
    # 75-100 = BUY candidate
    # 50-74  = HOLD / WAIT
    # below 50 = NO TRADE

    if score >= 75:
        analysis.decision = "BUY"

    elif score >= 50:
        analysis.decision = "HOLD"

    else:
        analysis.decision = "NO-TRADE"

    return analysis


# ============================================================
# POSITION PROTECTION
# ============================================================

def check_position_exit(
    position: Position,
    analysis: TokenAnalysis,
) -> Optional[str]:

    current_price = analysis.price_usd

    if current_price <= 0:
        return "Invalid price"

    # Update highest observed price
    if current_price > position.highest_price:
        position.highest_price = current_price

    pnl_percent = (
        (current_price - position.entry_price)
        / position.entry_price
    ) * 100

    # --------------------------------------------------------
    # HARD STOP LOSS
    # --------------------------------------------------------

    if pnl_percent <= -STOP_LOSS_PERCENT:
        return (
            f"Stop loss triggered "
            f"({pnl_percent:.2f}%)"
        )

    # --------------------------------------------------------
    # LIQUIDITY EMERGENCY EXIT
    # --------------------------------------------------------

    if analysis.liquidity_usd < MIN_LIQUIDITY_USD * 0.50:
        return "Liquidity emergency"

    # --------------------------------------------------------
    # HEAVY SELLING
    # --------------------------------------------------------

    total = (
        analysis.buys_5m +
        analysis.sells_5m
    )

    if total >= 10:

        sell_ratio = (
            analysis.sells_5m / total
        )

        if sell_ratio >= 0.85:
            return "Extreme selling pressure"

    # --------------------------------------------------------
    # TAKE PROFIT
    # --------------------------------------------------------

    if pnl_percent >= TAKE_PROFIT_PERCENT:
        return (
            f"Take profit reached "
            f"({pnl_percent:.2f}%)"
        )

    # --------------------------------------------------------
    # TRAILING STOP
    # --------------------------------------------------------

    if (
        position.highest_price >
        position.entry_price * 1.10
    ):

        drop_from_high = (
            (
                position.highest_price -
                current_price
            )
            / position.highest_price
        ) * 100

        if drop_from_high >= TRAILING_STOP_PERCENT:
            return (
                f"Trailing stop triggered "
                f"({drop_from_high:.2f}% from high)"
            )

    return None


# ============================================================
# DISCORD BOT
# ============================================================

intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(
    command_prefix="!",
    intents=intents,
)


# ============================================================
# DISCORD EVENTS
# ============================================================

@bot.event
async def on_ready():

    logger.info(
        "PHANTOM AI TRADER ONLINE | User=%s",
        bot.user,
    )

    try:
        synced = await bot.tree.sync()

        logger.info(
            "SYNCED %s SLASH COMMAND(S)",
            len(synced),
        )

    except Exception as exc:
        logger.error(
            "COMMAND SYNC ERROR | %s",
            exc,
        )

    if not monitor_positions.is_running():
        monitor_positions.start()


# ============================================================
# /status
# ============================================================

@bot.tree.command(
    name="status",
    description="Show Phantom AI Trader status",
)
async def status(interaction: discord.Interaction):

    equity = portfolio.total_equity({})

    mode = (
        "LIVE TRADING"
        if LIVE_TRADING
        else "PAPER TRADING"
    )

    embed = discord.Embed(
        title="🤖 Phantom AI Trader",
        description="AI risk engine status",
    )

    embed.add_field(
        name="Mode",
        value=mode,
        inline=True,
    )

    embed.add_field(
        name="Cash",
        value=f"${portfolio.cash:,.2f}",
        inline=True,
    )

    embed.add_field(
        name="Positions",
        value=str(len(portfolio.positions)),
        inline=True,
    )

    embed.add_field(
        name="Equity",
        value=f"${equity:,.2f}",
        inline=True,
    )

    embed.add_field(
        name="Live Trading",
        value=str(LIVE_TRADING),
        inline=True,
    )

    await interaction.response.send_message(
        embed=embed,
        ephemeral=True,
    )


# ============================================================
# /analyze
# ============================================================

@bot.tree.command(
    name="analyze",
    description="Analyze a Solana token",
)
@app_commands.describe(
    token="Solana token mint address",
)
async def analyze(
    interaction: discord.Interaction,
    token: str,
):

    await interaction.response.defer()

    logger.info(
        "ANALYZE | TOKEN=%s | USER=%s",
        token,
        interaction.user,
    )

    analysis = await fetch_token(token)

    if not analysis:

        await interaction.followup.send(
            "❌ I couldn't find usable Solana market data for that token."
        )

        return

    analysis = analyze_risk(analysis)

    reasons = (
        "\n".join(
            f"• {reason}"
            for reason in analysis.reasons
        )
        if analysis.reasons
        else "No major negative signals detected."
    )

    embed = discord.Embed(
        title=f"🧠 {analysis.symbol} Risk Analysis",
    )

    embed.add_field(
        name="Decision",
        value=analysis.decision,
        inline=True,
    )

    embed.add_field(
        name="Risk Score",
        value=f"{analysis.risk_score}/100",
        inline=True,
    )

    embed.add_field(
        name="Price",
        value=f"${analysis.price_usd:.10f}",
        inline=True,
    )

    embed.add_field(
        name="Liquidity",
        value=f"${analysis.liquidity_usd:,.0f}",
        inline=True,
    )

    embed.add_field(
        name="24h Volume",
        value=f"${analysis.volume_24h:,.0f}",
        inline=True,
    )

    embed.add_field(
        name="5m Change",
        value=f"{analysis.price_change_5m:.2f}%",
        inline=True,
    )

    embed.add_field(
        name="5m Buys / Sells",
        value=(
            f"{analysis.buys_5m} / "
            f"{analysis.sells_5m}"
        ),
        inline=True,
    )

    embed.add_field(
        name="Risk Signals",
        value=reasons[:1024],
        inline=False,
    )

    await interaction.followup.send(
        embed=embed
    )


# ============================================================
# /paperbuy
# ============================================================

@bot.tree.command(
    name="paperbuy",
    description="Simulate buying a token",
)
@app_commands.describe(
    token="Solana token mint address",
    amount="USD amount",
)
async def paperbuy(
    interaction: discord.Interaction,
    token: str,
    amount: float,
):

    await interaction.response.defer()

    analysis = await fetch_token(token)

    if not analysis:

        await interaction.followup.send(
            "❌ Could not retrieve token data."
        )

        return

    analysis = analyze_risk(analysis)

    # The risk engine gets the final say.
    if analysis.decision != "BUY":

        await interaction.followup.send(
            f"🛑 Trade rejected.\n\n"
            f"Decision: **{analysis.decision}**\n"
            f"Risk score: **{analysis.risk_score}/100**\n\n"
            f"The bot will not force a trade."
        )

        return

    # Position sizing safety limit
    max_allowed = (
        portfolio.cash *
        (MAX_POSITION_PERCENT / 100)
    )

    if amount > max_allowed:

        await interaction.followup.send(
            f"🛑 Position too large.\n"
            f"Maximum allowed: **${max_allowed:,.2f}**"
        )

        return

    success, message = portfolio.buy(
        analysis,
        amount,
    )

    await interaction.followup.send(
        f"{'✅' if success else '❌'} {message}"
    )


# ============================================================
# /positions
# ============================================================

@bot.tree.command(
    name="positions",
    description="Show current paper positions",
)
async def positions(
    interaction: discord.Interaction,
):

    if not portfolio.positions:

        await interaction.response.send_message(
            "📭 No open positions.",
            ephemeral=True,
        )

        return

    lines = []

    for position in portfolio.positions.values():

        lines.append(
            f"**{position.symbol}**\n"
            f"Entry: `${position.entry_price:.10f}`\n"
            f"Invested: `${position.invested_usd:,.2f}`"
        )

    await interaction.response.send_message(
        "\n\n".join(lines),
        ephemeral=True,
    )


# ============================================================
# /panic
# ============================================================

@bot.tree.command(
    name="panic",
    description="Emergency stop for automated trading",
)
async def panic(
    interaction: discord.Interaction,
):

    # This does not sell anything yet.
    # It prevents future automated execution.
    global LIVE_TRADING

    LIVE_TRADING = False

    logger.warning(
        "PANIC STOP ACTIVATED | USER=%s",
        interaction.user,
    )

    await interaction.response.send_message(
        "🚨 **PANIC STOP ACTIVATED**\n"
        "Live trading has been disabled.",
        ephemeral=True,
    )


# ============================================================
# AUTOMATIC POSITION MONITOR
# ============================================================

@tasks.loop(seconds=20)
async def monitor_positions():

    if not portfolio.positions:
        return

    addresses = list(
        portfolio.positions.keys()
    )

    for address in addresses:

        position = portfolio.positions.get(address)

        if not position:
            continue

        analysis = await fetch_token(address)

        if not analysis:
            continue

        reason = check_position_exit(
            position,
            analysis,
        )

        if reason:

            success, message = portfolio.sell(
                analysis,
                reason,
            )

            if success:

                logger.warning(
                    "AUTOMATIC EXIT | %s",
                    message,
                )


@monitor_positions.before_loop
async def before_monitor():

    await bot.wait_until_ready()


# ============================================================
# STARTUP
# ============================================================

if not DISCORD_TOKEN:

    raise RuntimeError(
        "DISCORD_TOKEN environment variable is missing."
    )


logger.info(
    "=================================================="
)

logger.info(
    "PHANTOM AI TRADER STARTING"
)

logger.info(
    "TRADING MODE | %s",
    "LIVE" if LIVE_TRADING else "PAPER",
)

logger.info(
    "LIVE TRADING SAFETY | %s",
    LIVE_TRADING,
)

logger.info(
    "MAX POSITION | %.2f%%",
    MAX_POSITION_PERCENT,
)

logger.info(
    "STOP LOSS | %.2f%%",
    STOP_LOSS_PERCENT,
)

logger.info(
    "TAKE PROFIT | %.2f%%",
    TAKE_PROFIT_PERCENT,
)

logger.info(
    "=================================================="
)

bot.run(DISCORD_TOKEN)
