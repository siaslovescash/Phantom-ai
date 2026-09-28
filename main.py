import os
import logging

import discord
from discord import app_commands
from discord.ext import commands

from risk_engine import analyze_token


# ============================================================
# CONFIG
# ============================================================

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")

LIVE_TRADING = (
    os.getenv("LIVE_TRADING", "false").lower() == "true"
)

PAPER_BALANCE = float(
    os.getenv("PAPER_BALANCE_USD", "1000")
)


# ============================================================
# LOGGING
# ============================================================

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s | %(message)s",
)

logger = logging.getLogger("phantom-ai-trader")


# ============================================================
# PAPER PORTFOLIO
# ============================================================

paper_cash = PAPER_BALANCE
positions = {}


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
# BOT READY
# ============================================================

@bot.event
async def on_ready():

    logger.info("==========================================")
    logger.info("PHANTOM AI TRADER ONLINE")
    logger.info("BOT USER: %s", bot.user)
    logger.info(
        "TRADING MODE: %s",
        "LIVE" if LIVE_TRADING else "PAPER",
    )
    logger.info("PAPER BALANCE: $%.2f", paper_cash)
    logger.info("==========================================")

    try:

        synced = await bot.tree.sync()

        logger.info(
            "SYNCED %s SLASH COMMAND(S)",
            len(synced),
        )

        for command in synced:
            logger.info(
                "REGISTERED: /%s",
                command.name,
            )

    except Exception as exc:

        logger.exception(
            "COMMAND SYNC ERROR: %s",
            exc,
        )


# ============================================================
# /status
# ============================================================

@bot.tree.command(
    name="status",
    description="Show Phantom AI Trader status",
)
async def status(
    interaction: discord.Interaction,
):

    mode = (
        "🔴 LIVE TRADING"
        if LIVE_TRADING
        else "🟢 PAPER TRADING"
    )

    embed = discord.Embed(
        title="🤖 Phantom AI Trader",
        description="Current bot status",
    )

    embed.add_field(
        name="Mode",
        value=mode,
        inline=True,
    )

    embed.add_field(
        name="Paper Cash",
        value=f"${paper_cash:,.2f}",
        inline=True,
    )

    embed.add_field(
        name="Open Positions",
        value=str(len(positions)),
        inline=True,
    )

    embed.add_field(
        name="Risk Engine",
        value="🟢 ONLINE",
        inline=True,
    )

    embed.add_field(
        name="Real Wallet",
        value="🔒 NOT CONNECTED",
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
    description="Run the AI risk engine on a Solana token",
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
        "ANALYSIS REQUEST | TOKEN=%s | USER=%s",
        token,
        interaction.user,
    )

    try:

        report = await analyze_token(token)

    except Exception as exc:

        logger.exception(
            "RISK ENGINE ERROR: %s",
            exc,
        )

        await interaction.followup.send(
            "❌ The risk engine encountered an error."
        )

        return

    if report.decision == "BUY-CANDIDATE":

        decision_text = "🟢 BUY CANDIDATE"

    elif report.decision == "WAIT":

        decision_text = "🟡 WAIT"

    else:

        decision_text = "🔴 NO TRADE"

    embed = discord.Embed(
        title="🧠 Phantom AI Risk Analysis",
        description=(
            f"**{report.decision}**\n"
            f"{decision_text}"
        ),
    )

    embed.add_field(
        name="Risk Score",
        value=f"{report.risk_score}/100",
        inline=True,
    )

    embed.add_field(
        name="Risk Level",
        value=report.risk_level,
        inline=True,
    )

    embed.add_field(
        name="Liquidity",
        value=f"${report.liquidity_usd:,.0f}",
        inline=True,
    )

    embed.add_field(
        name="24h Volume",
        value=f"${report.volume_24h_usd:,.0f}",
        inline=True,
    )

    embed.add_field(
        name="Market Cap",
        value=f"${report.market_cap_usd:,.0f}",
        inline=True,
    )

    if report.top_holder_percent is not None:

        holder_text = (
            f"{report.top_holder_percent:.2f}%"
        )

    else:

        holder_text = "Unavailable"

    embed.add_field(
        name="Top Holder",
        value=holder_text,
        inline=True,
    )

    # --------------------------------------------------------
    # RISK REASONS
    # --------------------------------------------------------

    if report.reasons:

        reasons_text = "\n".join(
            f"• {reason}"
            for reason in report.reasons
        )

    else:

        reasons_text = (
            "No major negative signals returned."
        )

    embed.add_field(
        name="Risk Signals",
        value=reasons_text[:1024],
        inline=False,
    )

    # --------------------------------------------------------
    # WARNINGS
    # --------------------------------------------------------

    if report.warnings:

        warnings_text = "\n".join(
            f"• {warning}"
            for warning in report.warnings
        )

        embed.add_field(
            name="Warnings",
            value=warnings_text[:1024],
            inline=False,
        )

    embed.set_footer(
        text=(
            "Risk analysis is not a guarantee against "
            "loss or a rug."
        )
    )

    await interaction.followup.send(
        embed=embed
    )


# ============================================================
# /paperbuy
# ============================================================

@bot.tree.command(
    name="paperbuy",
    description="Simulate a trade after risk analysis",
)
@app_commands.describe(
    token="Solana token mint address",
    amount="USD amount to simulate",
)
async def paperbuy(
    interaction: discord.Interaction,
    token: str,
    amount: float,
):

    global paper_cash

    await interaction.response.defer()

    # --------------------------------------------------------
    # BASIC AMOUNT CHECK
    # --------------------------------------------------------

    if amount <= 0:

        await interaction.followup.send(
            "❌ Amount must be greater than $0."
        )

        return

    # Maximum paper position = 5% of starting balance
    max_position = PAPER_BALANCE * 0.05

    if amount > max_position:

        await interaction.followup.send(
            f"🛑 Position rejected.\n\n"
            f"Maximum paper position: "
            f"**${max_position:,.2f}**"
        )

        return

    if amount > paper_cash:

        await interaction.followup.send(
            "❌ Insufficient paper balance."
        )

        return

    # --------------------------------------------------------
    # RUN RISK ENGINE
    # --------------------------------------------------------

    try:

        report = await analyze_token(token)

    except Exception as exc:

        logger.exception(
            "PAPER BUY ANALYSIS ERROR: %s",
            exc,
        )

        await interaction.followup.send(
            "❌ Risk analysis failed. "
            "Trade rejected for safety."
        )

        return

    # --------------------------------------------------------
    # RISK ENGINE MUST APPROVE
    # --------------------------------------------------------

    if report.decision != "BUY-CANDIDATE":

        await interaction.followup.send(
            f"🛑 **TRADE REJECTED**\n\n"
            f"Decision: **{report.decision}**\n"
            f"Risk score: **{report.risk_score}/100**\n"
            f"Risk level: **{report.risk_level}**\n\n"
            f"The bot will not force a trade."
        )

        return

    # --------------------------------------------------------
    # PAPER TRADE
    # --------------------------------------------------------

    paper_cash -= amount

    positions[token] = {
        "amount": amount,
        "entry_price": 0,
        "symbol": token[:8],
    }

    logger.info(
        "PAPER BUY | TOKEN=%s | AMOUNT=$%.2f | RISK=%s",
        token,
        amount,
        report.risk_score,
    )

    await interaction.followup.send(
        f"🟢 **PAPER BUY APPROVED**\n\n"
        f"Amount: **${amount:,.2f}**\n"
        f"Risk score: **{report.risk_score}/100**\n"
        f"Risk level: **{report.risk_level}**\n\n"
        f"💵 Remaining paper cash: "
        f"**${paper_cash:,.2f}**\n\n"
        f"⚠️ No real funds were used."
    )


# ============================================================
# /positions
# ============================================================

@bot.tree.command(
    name="positions",
    description="Show open paper positions",
)
async def show_positions(
    interaction: discord.Interaction,
):

    if not positions:

        await interaction.response.send_message(
            "📭 No open paper positions.",
            ephemeral=True,
        )

        return

    lines = []

    for token, position in positions.items():

        lines.append(
            f"**Token:** `{token}`\n"
            f"Invested: **${position['amount']:,.2f}**"
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
    description="Emergency disable for live trading",
)
async def panic(
    interaction: discord.Interaction,
):

    global LIVE_TRADING

    LIVE_TRADING = False

    logger.warning(
        "PANIC STOP | USER=%s",
        interaction.user,
    )

    await interaction.response.send_message(
        "🚨 **PANIC STOP ACTIVATED**\n\n"
        "Live trading is disabled.",
        ephemeral=True,
    )


# ============================================================
# STARTUP
# ============================================================

if not DISCORD_TOKEN:

    raise RuntimeError(
        "DISCORD_TOKEN environment variable is missing."
    )


logger.info(
    "PHANTOM AI TRADER STARTING..."
)

logger.info(
    "LIVE_TRADING=%s",
    LIVE_TRADING,
)

logger.info(
    "RISK ENGINE=ENABLED"
)

logger.info(
    "REAL WALLET=NOT CONNECTED"
)

bot.run(DISCORD_TOKEN)
