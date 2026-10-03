"""
ELT Welcome Bot
=======================================
Sends a styled welcome message (embed + animated banner) when a member joins, or - better for
a server with verification - the moment they get VERIFIED.

What the message contains:
    - the member is @mentioned (they get a ping) above the embed
    - their avatar + name, member number, account age, join time
    - quick-start links to rules / announcements / roles / chat (only the ones you set)
    - the animated banner (Liebe_Roxo.gif) at the bottom

Requirements:
    pip install "discord.py>=2.4"

Before running:
    - Put Liebe_Roxo.gif in the SAME folder as this file (upload both to Railway/GitHub).
    - Enable SERVER MEMBERS INTENT for the bot in the Discord Developer Portal.
    - Give the bot View Channel, Send Messages, Embed Links and Attach Files in the welcome channel.
    - Set DISCORD_TOKEN as an environment variable (Railway > Variables).
    - Fill in WELCOME_CHANNEL_ID (and the other channel IDs) below:
      right-click a channel -> Copy Channel ID.

Test it without anyone joining: type /testwelcome (administrators only). It shows you a private
preview and pings nobody.
"""

from __future__ import annotations

import os
import time

import discord
from discord import app_commands
from discord.ext import commands

# =========================== CONFIG ===========================
TOKEN = os.environ.get("DISCORD_TOKEN")

GUILD_ID = 1410440666747633707  # ELT server ID
SERVER_NAME = "ELT | ELITE LEADERS COMMUNITY"

# Where the welcome message is posted (REQUIRED - paste the channel ID).
WELCOME_CHANNEL_ID: int | None = 1513904242891427930

# Quick-start links shown in the message. Leave a line as None to hide it.
RULES_CHANNEL_ID: int | None = 1410440667401814052
ANNOUNCEMENTS_CHANNEL_ID: int | None = 1513930984456716458
ROLES_CHANNEL_ID: int | None = None
CHAT_CHANNEL_ID: int | None = 1513904263502499870

# When to welcome someone:
#   "verified" -> right after a moderator verifies them (they get the Verified role)
#   "join"     -> the moment they join the server
WELCOME_TRIGGER = "verified"
VERIFIED_ROLE_ID = 1513904156350353511

# The animated banner (must sit next to this file). If the file is missing, the message is
# sent without it.
BANNER_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "Liebe_Roxo.gif")

EMBED_COLOR = 0x9B30FF   # purple, matches the banner
# Anti-spam: the same member is never welcomed twice within this many seconds
# (stops spam if someone keeps leaving and re-joining).
WELCOME_COOLDOWN = 10 * 60
# ================================================================

intents = discord.Intents.default()
intents.members = True  # needed to see joins and role changes (enable in the Developer Portal)

bot = commands.Bot(command_prefix="!", intents=intents)

_last_welcome: dict[int, float] = {}


def ordinal(n: int) -> str:
    """1 -> 1st, 2 -> 2nd, 3 -> 3rd, 11 -> 11th ..."""
    suffix = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n:,}{suffix}"


def build_welcome(member: discord.Member) -> tuple[discord.Embed, discord.File | None]:
    guild = member.guild
    count = guild.member_count or len(guild.members)

    # Quick-start links (only the ones that are set).
    links = []
    if RULES_CHANNEL_ID:
        links.append(f"📜 **Read the rules** — <#{RULES_CHANNEL_ID}>")
    if ANNOUNCEMENTS_CHANNEL_ID:
        links.append(f"📢 **Stay updated** — <#{ANNOUNCEMENTS_CHANNEL_ID}>")
    if ROLES_CHANNEL_ID:
        links.append(f"🎭 **Choose your roles** — <#{ROLES_CHANNEL_ID}>")
    if CHAT_CHANNEL_ID:
        links.append(f"💬 **Meet the community** — <#{CHAT_CHANNEL_ID}>")
    links_text = "\n".join(links)

    description = (
        f"## Welcome, {member.mention}\n"
        "*Step inside… and remain as long as you dare.*\n"
        "\n"
        f"Your presence has been expected. You are our **{ordinal(count)}** member, "
        "and the community just grew stronger.\n"
    )
    if links_text:
        description += f"\n### Begin your journey\n{links_text}\n"
    description += (
        "\n"
        "> Respect everyone, keep it fun, and follow the rules. "
        "If you ever need help, join **Waiting for Help** and a **moderator** will be with you."
    )

    embed = discord.Embed(
        title="✦ WELCOME TO ELITE LEADERS COMMUNITY ✦",
        description=description,
        color=EMBED_COLOR,
    )
    embed.set_author(name=member.display_name, icon_url=member.display_avatar.url)
    embed.set_thumbnail(url=member.display_avatar.url)
    embed.add_field(name="Member", value=member.mention, inline=True)
    embed.add_field(name="Account Created", value=discord.utils.format_dt(member.created_at, "R"), inline=True)
    embed.add_field(name="Member Number", value=f"`#{count:,}`", inline=True)
    embed.set_footer(
        text=f"{SERVER_NAME} • Welcome aboard",
        icon_url=guild.icon.url if guild.icon else None,
    )
    embed.timestamp = discord.utils.utcnow()

    file = None
    if os.path.exists(BANNER_FILE):
        file = discord.File(BANNER_FILE, filename="welcome.gif")
        embed.set_image(url="attachment://welcome.gif")
    else:
        print(f"⚠️ Banner not found at {BANNER_FILE} — sending the welcome without it")
    return embed, file


async def send_welcome(member: discord.Member):
    if member.bot or member.guild.id != GUILD_ID:
        return

    now = time.monotonic()
    if now - _last_welcome.get(member.id, -1e9) < WELCOME_COOLDOWN:
        print(f"⏭️ {member} was welcomed recently — skipped")
        return
    _last_welcome[member.id] = now

    channel = member.guild.get_channel(WELCOME_CHANNEL_ID) if WELCOME_CHANNEL_ID else None
    if not isinstance(channel, discord.abc.Messageable):
        print("⚠️ Set WELCOME_CHANNEL_ID to the channel where welcomes should be posted")
        return

    embed, file = build_welcome(member)
    try:
        await channel.send(
            content=member.mention,
            embed=embed,
            file=file if file else discord.utils.MISSING,
            allowed_mentions=discord.AllowedMentions(users=[member]),
        )
        print(f"✅ Welcomed {member}")
    except discord.HTTPException as e:
        print(f"❌ Failed to send the welcome for {member}: {e}")


@bot.event
async def setup_hook():
    guild = discord.Object(id=GUILD_ID)
    bot.tree.copy_global_to(guild=guild)
    await bot.tree.sync(guild=guild)


@bot.event
async def on_ready():
    print(f"✅ Logged in as {bot.user} (ID: {bot.user.id}) — welcome trigger: {WELCOME_TRIGGER}")


@bot.event
async def on_member_join(member: discord.Member):
    if WELCOME_TRIGGER == "join":
        await send_welcome(member)


@bot.event
async def on_member_update(before: discord.Member, after: discord.Member):
    if WELCOME_TRIGGER != "verified":
        return
    role = after.guild.get_role(VERIFIED_ROLE_ID)
    if role and role not in before.roles and role in after.roles:
        await send_welcome(after)


@bot.tree.command(name="testwelcome", description="Preview the welcome message (only you can see it)")
@app_commands.default_permissions(administrator=True)
async def testwelcome(interaction: discord.Interaction):
    embed, file = build_welcome(interaction.user)
    await interaction.response.send_message(
        embed=embed,
        file=file if file else discord.utils.MISSING,
        ephemeral=True,
    )


if not TOKEN:
    raise SystemExit("DISCORD_TOKEN is not set. Add it in Railway's Variables tab, then redeploy.")

bot.run(TOKEN)
