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
WELCOME_TRIGGER = "join"
VERIFIED_ROLE_ID = 1513904156350353511
 
# Voice channel a new member joins to get verified ("Waiting for Move").
VERIFY_VC_ID: int | None = 1513904254535073883
 
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
 
bot = commands.Bot(command_prefix=commands.when_mentioned, intents=intents)  # no prefix commands -> no message-content warning
 
_last_welcome: dict[int, float] = {}
 
 
def ordinal(n: int) -> str:
    """1 -> 1st, 2 -> 2nd, 3 -> 3rd, 11 -> 11th ..."""
    suffix = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n:,}{suffix}"
 
 
def build_welcome(member: discord.Member) -> tuple[discord.Embed, discord.File | None]:
    guild = member.guild
    count = guild.member_count or len(guild.members)
 
    E = "<a:emoji_8128:1556021990324969592>"
 
    # Quick-start links (only the ones that are set).
    links = []
    if RULES_CHANNEL_ID:
        links.append(f"{E} **Rules** ➜ <#{RULES_CHANNEL_ID}>")
    if ANNOUNCEMENTS_CHANNEL_ID:
        links.append(f"{E} **Announcements** ➜ <#{ANNOUNCEMENTS_CHANNEL_ID}>")
    if ROLES_CHANNEL_ID:
        links.append(f"{E} **Roles** ➜ <#{ROLES_CHANNEL_ID}>")
    if CHAT_CHANNEL_ID:
        links.append(f"{E} **Chat** ➜ <#{CHAT_CHANNEL_ID}>")
    links_text = "\n".join(links)
 
    description = (
        "# ✦ WELCOME TO ELITE LEADERS COMMUNITY ✦\n"
        f"## {member.mention}\n"
        "*Step inside… and remain as long as you dare.*\n"
        "\n"
        f"> You are our `{ordinal(count)}` member.\n"
        "> The community just grew **stronger**.\n"
    )
    if links_text:
        description += f"\n### Begin your journey\n{links_text}\n"
    if VERIFY_VC_ID:
        description += (
            "\n### How to verify\n"
            f"> **1.** Join the voice channel <#{VERIFY_VC_ID}>\n"
            "> **2.** Wait a moment — a **staff member** will verify you\n"
            "> **3.** Once verified, the **whole server opens** for you\n"
        )
 
    embed = discord.Embed(description=description, color=EMBED_COLOR)
    embed.set_author(name=member.display_name, icon_url=member.display_avatar.url)
    embed.set_thumbnail(url=member.display_avatar.url)
    embed.add_field(name="Member", value=f"`{member.display_name}`", inline=True)
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
 
 
async def send_welcome(member: discord.Member, force: bool = False) -> str | None:
    """Posts the welcome. Returns None on success, or a short text saying why nothing was sent."""
    if member.bot:
        return "bots are not welcomed"
    if member.guild.id != GUILD_ID:
        return f"wrong server (GUILD_ID is {GUILD_ID})"
 
    now = time.monotonic()
    if not force and now - _last_welcome.get(member.id, -1e9) < WELCOME_COOLDOWN:
        print(f"⏭️ {member} was welcomed recently — skipped")
        return "welcomed recently (cooldown)"
    _last_welcome[member.id] = now
 
    channel = member.guild.get_channel(WELCOME_CHANNEL_ID) if WELCOME_CHANNEL_ID else None
    if not isinstance(channel, discord.abc.Messageable):
        print(f"❌ Can't find the welcome channel {WELCOME_CHANNEL_ID} — wrong ID, or the bot can't see it")
        return "the bot can't see the welcome channel"
 
    embed, file = build_welcome(member)
    try:
        await channel.send(
            content=member.mention,
            embed=embed,
            file=file if file else discord.utils.MISSING,
            allowed_mentions=discord.AllowedMentions(users=[member]),
        )
        print(f"✅ Welcomed {member}")
        return None
    except discord.Forbidden:
        print("❌ Missing permissions in the welcome channel (need View Channel, Send Messages, Embed Links, Attach Files)")
        return "the bot is missing permissions in the welcome channel"
    except discord.HTTPException as e:
        print(f"❌ Failed to send the welcome for {member}: {e}")
        return f"Discord error: {e}"
 
 
@bot.event
async def setup_hook():
    await bot.load_extension("server_logs")  # server logs (server_logs.py)
    guild = discord.Object(id=GUILD_ID)
    bot.tree.copy_global_to(guild=guild)
    await bot.tree.sync(guild=guild)
 
 
@bot.event
async def on_ready():
    print(f"✅ Logged in as {bot.user} (ID: {bot.user.id}) — welcome trigger: {WELCOME_TRIGGER}")
    guild = bot.get_guild(GUILD_ID)
    if guild is None:
        print(f"❌ The bot is not in the server {GUILD_ID} — check GUILD_ID and that the bot was invited")
        return
    channel = guild.get_channel(WELCOME_CHANNEL_ID) if WELCOME_CHANNEL_ID else None
    if channel is None:
        print(f"❌ Can't see the welcome channel {WELCOME_CHANNEL_ID} — wrong ID, or the bot lacks View Channel")
        return
    perms = channel.permissions_for(guild.me)
    missing = [
        name for name, ok in (
            ("View Channel", perms.view_channel),
            ("Send Messages", perms.send_messages),
            ("Embed Links", perms.embed_links),
            ("Attach Files", perms.attach_files),
        ) if not ok
    ]
    if missing:
        print(f"⚠️ Missing permissions in #{channel.name}: {', '.join(missing)}")
    else:
        print(f"✅ Welcome channel OK: #{channel.name}")
 
 
@bot.event
async def on_member_join(member: discord.Member):
    if WELCOME_TRIGGER == "join":
        await send_welcome(member)
 
 
@bot.event
async def on_member_update(before: discord.Member, after: discord.Member):
    if WELCOME_TRIGGER != "verified":
        return
    role = after.guild.get_role(VERIFIED_ROLE_ID)
    if role is None:
        print(f"⚠️ VERIFIED_ROLE_ID {VERIFIED_ROLE_ID} doesn't exist in the server")
        return
    if role not in before.roles and role in after.roles:
        print(f"🎖️ {after} got the Verified role — sending the welcome")
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
 
 
@bot.tree.command(name="sendwelcome", description="Send a REAL welcome for yourself in the welcome channel (test)")
@app_commands.default_permissions(administrator=True)
async def sendwelcome(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    problem = await send_welcome(interaction.user, force=True)
    await interaction.followup.send(
        "✅ Sent to the welcome channel." if problem is None else f"❌ Not sent: {problem}.",
        ephemeral=True,
    )
 
 
if not TOKEN:
    raise SystemExit("DISCORD_TOKEN is not set. Add it in Railway's Variables tab, then redeploy.")
 
bot.run(TOKEN)
 
