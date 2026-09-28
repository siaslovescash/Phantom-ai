import os
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import discord
from discord.ext import commands

from risk_engine import analyze_token


# ============================================================
# ENVIRONMENT
# ============================================================

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")

LIVE_TRADING = os.getenv("LIVE_TRADING", "false").lower() == "true"
PAPER_BALANCE = float(os.getenv("PAPER_BALANCE_USD", "1000"))

PORT = int(os.getenv("PORT", "10000"))


# ============================================================
# BASIC VALIDATION
# ============================================================

if not DISCORD_TOKEN:
    raise RuntimeError("DISCORD_TOKEN environment variable is missing.")


# ============================================================
# LOGGING
# ============================================================

print("=" * 60)
print("PHANTOM AI TRADER STARTING")
print("=" * 60)
print(f"LIVE_TRADING = {LIVE_TRADING}")
print(f"PAPER_BALANCE = ${PAPER_BALANCE:.2f}")
print("=" * 60)


# ============================================================
# RENDER HEALTH SERVER
# ============================================================

class HealthHandler(BaseHTTPRequestHandler):

    def do_GET(self):
        if self.path in ("/", "/health", "/health/"):
            response = b"Phantom AI Trader is running!"

            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Content-Length", str(len(response)))
            self.end_headers()

            self.wfile.write(response)

        else:
            response = b"Phantom AI Trader"

            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Content-Length", str(len(response)))
            self.end_headers()

            self.wfile.write(response)

    def log_message(self, format, *args):
        return


def start_health_server():
    server = HTTPServer(("0.0.0.0", PORT), HealthHandler)

    print(f"RENDER HEALTH SERVER STARTED | PORT={PORT}")

    server.serve_forever()


health_thread = threading.Thread(
    target=start_health_server,
    daemon=True
)

health_thread.start()


# ============================================================
# DISCORD INTENTS
# ============================================================

intents = discord.Intents.default()
intents.message_content = True


# ============================================================
# BOT
# ============================================================

bot = commands.Bot(
    command_prefix="!",
    intents=intents
)


# ============================================================
# PAPER TRADING DATA
# ============================================================

paper_balance = PAPER_BALANCE

paper_positions = {}


# ============================================================
# BOT READY
# ============================================================

@bot.event
async def on_ready():

    print("=" * 60)
    print(f"DISCORD CONNECTED | USER={bot.user}")
    print(f"GUILDS={len(bot.guilds)}")
    print("=" * 60)

    try:
        synced = await bot.tree.sync()

        print(f"SYNCED {len(synced)} SLASH COMMAND(S)")

        for command in synced:
            print(f"REGISTERED: /{command.name}")

    except Exception as error:
        print(f"SLASH COMMAND SYNC ERROR | {error}")


# ============================================================
# STATUS
# ============================================================

@bot.tree.command(
    name="status",
    description="Show Phantom AI Trader status"
)
async def status(interaction: discord.Interaction):

    print(
        f"EVENT: /status | "
        f"USER={interaction.user}"
    )

    mode = "LIVE TRADING" if LIVE_TRADING else "PAPER TRADING"

    await interaction.response.send_message(
        f"🤖 **Phantom AI Trader**\n\n"
        f"**Mode:** {mode}\n"
        f"**Paper Balance:** ${paper_balance:,.2f}\n"
        f"**Open Positions:** {len(paper_positions)}\n"
        f"**Risk Engine:** ONLINE\n"
        f"**Render Health Server:** ONLINE"
    )


# ============================================================
# ANALYZE TOKEN
# ============================================================

@bot.tree.command(
    name="analyze",
    description="Analyze a Solana token for trading risk"
)
async def analyze(
    interaction: discord.Interaction,
    token: str
):

    print(
        f"EVENT: /analyze | "
        f"USER={interaction.user} | "
        f"TOKEN={token}"
    )

    await interaction.response.defer()

    try:

        report = await analyze_token(token)

        message = (
            f"🔎 **TOKEN ANALYSIS**\n\n"
            f"**Token:** `{token}`\n"
            f"**Risk Score:** `{report.score}/100`\n"
            f"**Risk Level:** `{report.risk_level}`\n"
            f"**Decision:** `{report.decision}`\n\n"
            f"**Liquidity:** ${report.liquidity:,.2f}\n"
            f"**24h Volume:** ${report.volume_24h:,.2f}\n"
            f"**Market Cap:** ${report.market_cap:,.2f}\n"
            f"**Price:** ${report.price:.10f}\n\n"
            f"**Reasons:**\n"
        )

        if report.reasons:

            for reason in report.reasons[:10]:
                message += f"• {reason}\n"

        else:
            message += "• No additional risk reasons reported.\n"

        await interaction.followup.send(message)

        print(
            f"ANALYSIS COMPLETE | "
            f"TOKEN={token} | "
            f"SCORE={report.score} | "
            f"DECISION={report.decision}"
        )

    except Exception as error:

        print(
            f"ANALYSIS ERROR | "
            f"TOKEN={token} | "
            f"ERROR={error}"
        )

        await interaction.followup.send(
            f"❌ Analysis failed.\n"
            f"`{error}`"
        )


# ============================================================
# PAPER BUY
# ============================================================

@bot.tree.command(
    name="paperbuy",
    description="Simulate a token purchase"
)
async def paperbuy(
    interaction: discord.Interaction,
    token: str,
    amount: float
):

    global paper_balance

    print(
        f"EVENT: /paperbuy | "
        f"USER={interaction.user} | "
        f"TOKEN={token} | "
        f"AMOUNT=${amount:.2f}"
    )

    if LIVE_TRADING:

        await interaction.response.send_message(
            "⚠️ Live trading mode is enabled, but real execution "
            "is not connected yet."
        )

        return

    if amount <= 0:

        await interaction.response.send_message(
            "❌ Amount must be greater than $0."
        )

        return

    if amount > paper_balance:

        await interaction.response.send_message(
            f"❌ Insufficient paper balance.\n"
            f"Available: ${paper_balance:,.2f}"
        )

        return

    await interaction.response.defer()

    try:

        report = await analyze_token(token)

        if report.decision != "BUY-CANDIDATE":

            await interaction.followup.send(
                f"🛑 **PAPER BUY BLOCKED**\n\n"
                f"Token: `{token}`\n"
                f"Risk Score: `{report.score}/100`\n"
                f"Risk Level: `{report.risk_level}`\n"
                f"Decision: `{report.decision}`\n\n"
                f"The risk engine did not approve this token."
            )

            print(
                f"PAPER BUY BLOCKED | "
                f"TOKEN={token} | "
                f"DECISION={report.decision}"
            )

            return

        paper_balance -= amount

        if token in paper_positions:

            paper_positions[token]["amount_usd"] += amount

        else:

            paper_positions[token] = {
                "amount_usd": amount,
                "entry_price": report.price,
            }

        await interaction.followup.send(
            f"🟢 **PAPER BUY EXECUTED**\n\n"
            f"**Token:** `{token}`\n"
            f"**Amount:** ${amount:,.2f}\n"
            f"**Entry Price:** ${report.price:.10f}\n"
            f"**Risk Score:** {report.score}/100\n"
            f"**Remaining Balance:** ${paper_balance:,.2f}"
        )

        print(
            f"PAPER BUY COMPLETE | "
            f"TOKEN={token} | "
            f"AMOUNT=${amount:.2f} | "
            f"BALANCE=${paper_balance:.2f}"
        )

    except Exception as error:

        print(
            f"PAPER BUY ERROR | "
            f"TOKEN={token} | "
            f"ERROR={error}"
        )

        await interaction.followup.send(
            f"❌ Paper buy failed.\n"
            f"`{error}`"
        )


# ============================================================
# POSITIONS
# ============================================================

@bot.tree.command(
    name="positions",
    description="Show current paper trading positions"
)
async def positions(interaction: discord.Interaction):

    print(
        f"EVENT: /positions | "
        f"USER={interaction.user}"
    )

    if not paper_positions:

        await interaction.response.send_message(
            f"📊 **PAPER POSITIONS**\n\n"
            f"No open positions.\n\n"
            f"**Available Balance:** "
            f"${paper_balance:,.2f}"
        )

        return

    message = (
        f"📊 **PAPER POSITIONS**\n\n"
        f"**Available Balance:** ${paper_balance:,.2f}\n\n"
    )

    for token, position in paper_positions.items():

        message += (
            f"**{token}**\n"
            f"• Position: ${position['amount_usd']:,.2f}\n"
            f"• Entry: ${position['entry_price']:.10f}\n\n"
        )

    await interaction.response.send_message(message)


# ============================================================
# PANIC
# ============================================================

@bot.tree.command(
    name="panic",
    description="Close all paper trading positions"
)
async def panic(interaction: discord.Interaction):

    global paper_balance

    print(
        f"EVENT: /panic | "
        f"USER={interaction.user}"
    )

    total_closed = sum(
        position["amount_usd"]
        for position in paper_positions.values()
    )

    paper_balance += total_closed

    paper_positions.clear()

    await interaction.response.send_message(
        f"🚨 **PANIC MODE EXECUTED**\n\n"
        f"All paper positions have been closed.\n"
        f"Returned to paper balance: ${total_closed:,.2f}\n"
        f"Current balance: ${paper_balance:,.2f}\n\n"
        f"⚠️ No real trades were executed."
    )

    print(
        f"PANIC COMPLETE | "
        f"RETURNED=${total_closed:.2f} | "
        f"BALANCE=${paper_balance:.2f}"
    )


# ============================================================
# GLOBAL ERROR HANDLER
# ============================================================

@bot.event
async def on_error(event, *args, **kwargs):

    print(
        f"DISCORD EVENT ERROR | "
        f"EVENT={event}"
    )


# ============================================================
# START BOT
# ============================================================

print("STARTING DISCORD BOT...")

bot.run(DISCORD_TOKEN)
