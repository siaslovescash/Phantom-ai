import os
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
import discord
from discord.ext import commands
from risk_engine import analyze_token
# ============================================================
# CONFIGURATION
# ============================================================
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
LIVE_TRADING = os.getenv("LIVE_TRADING", "false").lower() == "true"
PAPER_BALANCE = float(
    os.getenv("PAPER_BALANCE_USD", "1000")
)
PORT = int(
    os.getenv("PORT", "10000")
)
# ============================================================
# STARTUP
# ============================================================
print("=" * 60, flush=True)
print("PHANTOM AI TRADER STARTING", flush=True)
print(f"LIVE_TRADING = {LIVE_TRADING}", flush=True)
print(f"PAPER_BALANCE = ${PAPER_BALANCE:.2f}", flush=True)
print(f"RENDER PORT = {PORT}", flush=True)
print("=" * 60, flush=True)
if not DISCORD_TOKEN:
    raise RuntimeError(
        "DISCORD_TOKEN environment variable is missing."
    )
# ============================================================
# RENDER HEALTH SERVER
# ============================================================
class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path in ("/", "/health", "/health/"):
            response = b"Phantom AI Trader is running!"
        elif self.path == "/status":
            response = b"Phantom AI Trader - ONLINE"
        else:
            response = b"Phantom AI Trader"
        self.send_response(200)
        self.send_header(
            "Content-Type",
            "text/plain"
        )
        self.send_header(
            "Content-Length",
            str(len(response))
        )
        self.end_headers()
        self.wfile.write(response)
    def log_message(self, format, *args):
        return
def start_health_server():
    try:
        server = HTTPServer(
            ("0.0.0.0", PORT),
            HealthHandler
        )
        print(
            f"RENDER HEALTH SERVER STARTED | "
            f"HOST=0.0.0.0 | "
            f"PORT={PORT}",
            flush=True
        )
        server.serve_forever()
    except Exception as error:
        print(
            f"RENDER HEALTH SERVER ERROR | {error}",
            flush=True
        )
health_thread = threading.Thread(
    target=start_health_server,
    daemon=True
)
health_thread.start()
print(
    "RENDER HEALTH SERVER THREAD STARTED",
    flush=True
)
# ============================================================
# DISCORD
# ============================================================
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(
    command_prefix="!",
    intents=intents
)
# ============================================================
# PAPER TRADING
# ============================================================
paper_balance = PAPER_BALANCE
paper_positions = {}
# ============================================================
# RISK SCORE COMPATIBILITY
# ============================================================
def get_risk_score(report):
    if hasattr(report, "risk_score"):
        return report.risk_score
    if hasattr(report, "score"):
        return report.score
    return 0
# ============================================================
# SAFE REPORT VALUE HELPERS
# ============================================================
def get_report_value(report, name, default=0):
    value = getattr(report, name, default)
    if value is None:
        return default
    return value
def get_report_reasons(report):
    reasons = getattr(report, "reasons", None)
    if reasons is None:
        return []
    return reasons
# ============================================================
# BOT READY
# ============================================================
@bot.event
async def on_ready():
    print(
        f"DISCORD CONNECTED | USER={bot.user}",
        flush=True
    )
    print(
        f"DISCORD GUILDS={len(bot.guilds)}",
        flush=True
    )
    try:
        synced = await bot.tree.sync()
        print(
            f"SYNCED {len(synced)} SLASH COMMAND(S)",
            flush=True
        )
        for command in synced:
            print(
                f"REGISTERED: /{command.name}",
                flush=True
            )
    except Exception as error:
        print(
            f"SLASH COMMAND SYNC ERROR | {error}",
            flush=True
        )
# ============================================================
# /STATUS
# ============================================================
@bot.tree.command(
    name="status",
    description="Show Phantom AI Trader status"
)
async def status(interaction: discord.Interaction):
    print(
        f"EVENT: /status | USER={interaction.user}",
        flush=True
    )
    mode = (
        "LIVE TRADING"
        if LIVE_TRADING
        else "PAPER TRADING"
    )
    await interaction.response.send_message(
        f"🤖 **Phantom AI Trader**\n\n"
        f"**Mode:** {mode}\n"
        f"**Paper Balance:** ${paper_balance:,.2f}\n"
        f"**Open Positions:** {len(paper_positions)}\n"
        f"**Risk Engine:** ONLINE\n"
        f"**Render Health Server:** ONLINE"
    )
# ============================================================
# /ANALYZE
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
        f"TOKEN={token}",
        flush=True
    )
    await interaction.response.defer()
    try:
        report = await analyze_token(token)
        risk_score = get_risk_score(report)
        risk_level = get_report_value(
            report,
            "risk_level",
            "UNKNOWN"
        )
        decision = get_report_value(
            report,
            "decision",
            "UNKNOWN"
        )
        liquidity = get_report_value(
            report,
            "liquidity",
            0
        )
        volume_24h = get_report_value(
            report,
            "volume_24h",
            0
        )
        market_cap = get_report_value(
            report,
            "market_cap",
            0
        )
        price = get_report_value(
            report,
            "price",
            0
        )
        reasons = get_report_reasons(report)
        message = (
            f"🔎 **TOKEN ANALYSIS**\n\n"
            f"**Token:** `{token}`\n"
            f"**Risk Score:** `{risk_score}/100`\n"
            f"**Risk Level:** `{risk_level}`\n"
            f"**Decision:** `{decision}`\n\n"
            f"**Liquidity:** "
            f"${liquidity:,.2f}\n"
            f"**24h Volume:** "
            f"${volume_24h:,.2f}\n"
            f"**Market Cap:** "
            f"${market_cap:,.2f}\n"
            f"**Price:** "
            f"${price:.10f}\n\n"
            f"**Reasons:**\n"
        )
        if reasons:
            for reason in reasons[:10]:
                message += f"• {reason}\n"
        else:
            message += (
                "• No additional risk reasons reported.\n"
            )
        await interaction.followup.send(message)
        print(
            f"ANALYSIS COMPLETE | "
            f"TOKEN={token} | "
            f"SCORE={risk_score} | "
            f"DECISION={decision}",
            flush=True
        )
    except Exception as error:
        print(
            f"ANALYSIS ERROR | "
            f"TOKEN={token} | "
            f"ERROR={error}",
            flush=True
        )
        await interaction.followup.send(
            f"❌ Analysis failed.\n"
            f"`{error}`"
        )
# ============================================================
# /PAPERBUY
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
        f"AMOUNT=${amount:.2f}",
        flush=True
    )
    if LIVE_TRADING:
        await interaction.response.send_message(
            "⚠️ Live trading mode is enabled, "
            "but real execution is not connected yet."
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
        decision = get_report_value(
            report,
            "decision",
            "NO-TRADE"
        )
        if decision != "BUY-CANDIDATE":
            risk_score = get_risk_score(report)
            risk_level = get_report_value(
                report,
                "risk_level",
                "UNKNOWN"
            )
            await interaction.followup.send(
                f"🛑 **PAPER BUY BLOCKED**\n\n"
                f"**Token:** `{token}`\n"
                f"**Risk Score:** `{risk_score}/100`\n"
                f"**Risk Level:** `{risk_level}`\n"
                f"**Decision:** `{decision}`\n\n"
                f"The risk engine did not approve "
                f"this token."
            )
            print(
                f"PAPER BUY BLOCKED | "
                f"TOKEN={token} | "
                f"DECISION={decision}",
                flush=True
            )
            return
        price = get_report_value(
            report,
            "price",
            0
        )
        paper_balance -= amount
        if token in paper_positions:
            paper_positions[token]["amount_usd"] += amount
        else:
            paper_positions[token] = {
                "amount_usd": amount,
                "entry_price": price
            }
        risk_score = get_risk_score(report)
        await interaction.followup.send(
            f"🟢 **PAPER BUY EXECUTED**\n\n"
            f"**Token:** `{token}`\n"
            f"**Amount:** ${amount:,.2f}\n"
            f"**Entry Price:** "
            f"${price:.10f}\n"
            f"**Risk Score:** "
            f"{risk_score}/100\n"
            f"**Remaining Balance:** "
            f"${paper_balance:,.2f}"
        )
        print(
            f"PAPER BUY COMPLETE | "
            f"TOKEN={token} | "
            f"AMOUNT=${amount:.2f} | "
            f"BALANCE=${paper_balance:.2f}",
            flush=True
        )
    except Exception as error:
        print(
            f"PAPER BUY ERROR | "
            f"TOKEN={token} | "
            f"ERROR={error}",
            flush=True
        )
        await interaction.followup.send(
            f"❌ Paper buy failed.\n"
            f"`{error}`"
        )
# ============================================================
# /POSITIONS
# ============================================================
@bot.tree.command(
    name="positions",
    description="Show current paper trading positions"
)
async def positions(
    interaction: discord.Interaction
):
    print(
        f"EVENT: /positions | "
        f"USER={interaction.user}",
        flush=True
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
        f"**Available Balance:** "
        f"${paper_balance:,.2f}\n\n"
    )
    for token, position in paper_positions.items():
        message += (
            f"**{token}**\n"
            f"• Position: "
            f"${position['amount_usd']:,.2f}\n"
            f"• Entry: "
            f"${position['entry_price']:.10f}\n\n"
        )
    await interaction.response.send_message(message)
# ============================================================
# /PANIC
# ============================================================
@bot.tree.command(
    name="panic",
    description="Close all paper trading positions"
)
async def panic(
    interaction: discord.Interaction
):
    global paper_balance
    print(
        f"EVENT: /panic | "
        f"USER={interaction.user}",
        flush=True
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
        f"Returned to paper balance: "
        f"${total_closed:,.2f}\n"
        f"Current balance: "
        f"${paper_balance:,.2f}\n\n"
        f"⚠️ No real trades were executed."
    )
    print(
        f"PANIC COMPLETE | "
        f"RETURNED=${total_closed:.2f} | "
        f"BALANCE=${paper_balance:.2f}",
        flush=True
    )
# ============================================================
# DISCORD ERROR HANDLER
# ============================================================
@bot.event
async def on_error(event, *args, **kwargs):
    print(
        f"DISCORD EVENT ERROR | EVENT={event}",
        flush=True
    )
# ============================================================
# START BOT
# ============================================================
print(
    "STARTING DISCORD BOT...",
    flush=True
)
bot.run(DISCORD_TOKEN)
