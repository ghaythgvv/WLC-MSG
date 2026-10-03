"""
ELT Server Logs (extension for the ELITE SYSTEM bot)
=======================================
Logs server events into the matching channel of your SERVER LOGS category:

    join / leave ............ -JOIN-LEAVES
    ban / unban ............. -BANS-UNBANS
    timeout / untimeout ..... -TIMEOUT
    kick .................... -KICK
    role given / removed .... -ROLE-GIVEN-REMOVED
    role created / deleted .. -ROLE-CREATED-DELETED
    channel created / deleted -CHANNEL-CREATED-DELETED
    everything .............. LOGS-ALL-SERVER

Channels are found automatically by their NAME (the emoji / symbols in front don't matter).
If you ever rename a channel, either keep the keyword in the name or paste its ID in
LOG_CHANNEL_IDS below.

The bot needs: View Audit Log (to show WHO did it) + View Channel / Send Messages / Embed Links
in each log channel. SERVER MEMBERS INTENT must be on (it already is for the welcome bot).

This file is loaded by welcome_bot.py:  await bot.load_extension("server_logs")
"""

from __future__ import annotations

import asyncio
import unicodedata

import discord
from discord.ext import commands

# =========================== CONFIG ===========================
GUILD_ID = 1410440666747633707  # ELT server ID

# key -> keyword that must appear in the channel name (lowercase)
CHANNEL_KEYWORDS = {
    "join_leave": "join-leaves",
    "ban": "bans-unbans",
    "timeout": "timeout",
    "kick": "kick",
    "role_member": "role-given-removed",
    "role_cd": "role-created-deleted",
    "channel_cd": "channel-created-deleted",
    "all": "logs-all-server",
}

# Optional: force a channel by ID instead of by name. Example: {"kick": 123456789}
LOG_CHANNEL_IDS: dict[str, int | None] = {}

COLOR_GOOD = 0x57F287   # green  (join, unban, role added, create)
COLOR_BAD = 0xED4245    # red    (leave, ban, kick, delete)
COLOR_WARN = 0xFEE75C   # yellow (timeout)
COLOR_INFO = 0x9B30FF   # purple
# ================================================================


def norm(text: str) -> str:
    """Fancy letters (𝗥𝗢𝗟𝗘), emoji and symbols are ignored: '┃𝗥𝗢𝗟𝗘-𝗚𝗜𝗩𝗘𝗡' -> 'rolegiven'."""
    text = unicodedata.normalize("NFKC", text).lower()
    return "".join(c for c in text if c.isalnum())


def who(user: discord.abc.Snowflake | None) -> str:
    if user is None:
        return "`Unknown`"
    mention = getattr(user, "mention", f"<@{user.id}>")
    return f"{mention} (`{user.id}`)"


class ServerLogs(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # ---------------------------------------------------------------- helpers
    def find_channel(self, guild: discord.Guild, key: str) -> discord.TextChannel | None:
        forced = LOG_CHANNEL_IDS.get(key)
        if forced:
            ch = guild.get_channel(forced)
            return ch if isinstance(ch, discord.TextChannel) else None
        keyword = norm(CHANNEL_KEYWORDS[key])
        for ch in guild.text_channels:
            if keyword in norm(ch.name):
                return ch
        return None

    @commands.Cog.listener()
    async def on_ready(self):
        """Prints in the Railway logs which log channels were found (and if the bot can write there)."""
        guild = self.bot.get_guild(GUILD_ID)
        if guild is None:
            print("❌ logs: server not found")
            return
        for key in CHANNEL_KEYWORDS:
            ch = self.find_channel(guild, key)
            if ch is None:
                print(f"❌ logs: no channel found for '{key}' (looking for '{CHANNEL_KEYWORDS[key]}')")
                continue
            perms = ch.permissions_for(guild.me)
            ok = perms.view_channel and perms.send_messages and perms.embed_links
            print(f"{'✅' if ok else '⚠️'} logs: {key} -> #{ch.name}" + ("" if ok else "  (bot can't send/embed here)"))
        if not guild.me.guild_permissions.view_audit_log:
            print("⚠️ logs: the bot is missing View Audit Log")

    async def log(self, guild: discord.Guild, key: str, embed: discord.Embed) -> None:
        """Send the embed to its own channel and to LOGS-ALL-SERVER."""
        embed.timestamp = discord.utils.utcnow()
        embed.set_footer(text="ELT Logs", icon_url=guild.icon.url if guild.icon else None)
        sent_to: set[int] = set()
        for k in (key, "all"):
            ch = self.find_channel(guild, k)
            if ch is None or ch.id in sent_to:
                continue
            sent_to.add(ch.id)
            try:
                await ch.send(embed=embed, allowed_mentions=discord.AllowedMentions.none())
            except discord.HTTPException as e:
                print(f"❌ Could not log to #{ch.name}: {e}")

    async def audit_entry(
        self,
        guild: discord.Guild,
        action: discord.AuditLogAction,
        target_id: int,
        within: float = 20.0,
    ) -> discord.AuditLogEntry | None:
        """Finds the audit log entry for an action that just happened (to show who did it)."""
        if not guild.me.guild_permissions.view_audit_log:
            return None
        await asyncio.sleep(2)  # Discord writes the audit log entry slightly after the event
        try:
            async for entry in guild.audit_logs(limit=15, action=action):
                if entry.target is not None and entry.target.id == target_id:
                    age = (discord.utils.utcnow() - entry.created_at).total_seconds()
                    if age <= within:
                        return entry
        except discord.HTTPException:
            pass
        return None

    @staticmethod
    def add_actor(embed: discord.Embed, entry: discord.AuditLogEntry | None) -> None:
        embed.add_field(name="By", value=who(entry.user) if entry else "`Unknown`", inline=True)
        if entry and entry.reason:
            embed.add_field(name="Reason", value=entry.reason[:1000], inline=False)

    # ---------------------------------------------------------------- join / leave
    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        if member.guild.id != GUILD_ID:
            return
        embed = discord.Embed(
            title="📥 Member Joined",
            description=f"{member.mention} joined the server.",
            color=COLOR_GOOD,
        )
        embed.set_thumbnail(url=member.display_avatar.url)
        embed.add_field(name="Member", value=who(member), inline=False)
        embed.add_field(name="Account Created", value=discord.utils.format_dt(member.created_at, "R"), inline=True)
        embed.add_field(name="Members Now", value=f"`{member.guild.member_count:,}`", inline=True)
        await self.log(member.guild, "join_leave", embed)

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member):
        guild = member.guild
        if guild.id != GUILD_ID:
            return

        embed = discord.Embed(
            title="📤 Member Left",
            description=f"{member.mention} left the server.",
            color=COLOR_BAD,
        )
        embed.set_thumbnail(url=member.display_avatar.url)
        embed.add_field(name="Member", value=who(member), inline=False)
        if member.joined_at:
            embed.add_field(name="Joined", value=discord.utils.format_dt(member.joined_at, "R"), inline=True)
        roles = [r.mention for r in member.roles if r != guild.default_role]
        if roles:
            embed.add_field(name="Roles", value=" ".join(roles)[:1000], inline=False)
        await self.log(guild, "join_leave", embed)

        # Was it a kick?
        entry = await self.audit_entry(guild, discord.AuditLogAction.kick, member.id)
        if entry:
            kick = discord.Embed(
                title="👢 Member Kicked",
                description=f"{member.mention} was kicked.",
                color=COLOR_BAD,
            )
            kick.set_thumbnail(url=member.display_avatar.url)
            kick.add_field(name="Member", value=who(member), inline=True)
            self.add_actor(kick, entry)
            await self.log(guild, "kick", kick)

    # ---------------------------------------------------------------- bans
    @commands.Cog.listener()
    async def on_member_ban(self, guild: discord.Guild, user: discord.User):
        if guild.id != GUILD_ID:
            return
        entry = await self.audit_entry(guild, discord.AuditLogAction.ban, user.id)
        embed = discord.Embed(title="🔨 Member Banned", description=f"{user.mention} was banned.", color=COLOR_BAD)
        embed.set_thumbnail(url=user.display_avatar.url)
        embed.add_field(name="Member", value=who(user), inline=True)
        self.add_actor(embed, entry)
        await self.log(guild, "ban", embed)

    @commands.Cog.listener()
    async def on_member_unban(self, guild: discord.Guild, user: discord.User):
        if guild.id != GUILD_ID:
            return
        entry = await self.audit_entry(guild, discord.AuditLogAction.unban, user.id)
        embed = discord.Embed(title="🔓 Member Unbanned", description=f"{user.mention} was unbanned.", color=COLOR_GOOD)
        embed.set_thumbnail(url=user.display_avatar.url)
        embed.add_field(name="Member", value=who(user), inline=True)
        self.add_actor(embed, entry)
        await self.log(guild, "ban", embed)

    # ---------------------------------------------------------------- roles on members + timeouts
    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member):
        guild = after.guild
        if guild.id != GUILD_ID:
            return

        # --- roles given / removed
        added = [r for r in after.roles if r not in before.roles]
        removed = [r for r in before.roles if r not in after.roles]
        if added or removed:
            entry = await self.audit_entry(guild, discord.AuditLogAction.member_role_update, after.id)
            embed = discord.Embed(
                title="🎭 Roles Updated",
                description=f"Roles changed for {after.mention}.",
                color=COLOR_INFO,
            )
            embed.set_thumbnail(url=after.display_avatar.url)
            embed.add_field(name="Member", value=who(after), inline=True)
            self.add_actor(embed, entry)
            if added:
                embed.add_field(name="➕ Added", value=" ".join(r.mention for r in added)[:1000], inline=False)
            if removed:
                embed.add_field(name="➖ Removed", value=" ".join(r.mention for r in removed)[:1000], inline=False)
            await self.log(guild, "role_member", embed)

        # --- timeout / untimeout
        if before.timed_out_until != after.timed_out_until:
            entry = await self.audit_entry(guild, discord.AuditLogAction.member_update, after.id)
            if after.timed_out_until and after.timed_out_until > discord.utils.utcnow():
                embed = discord.Embed(
                    title="⏳ Member Timed Out",
                    description=f"{after.mention} was timed out.",
                    color=COLOR_WARN,
                )
                embed.add_field(name="Ends", value=discord.utils.format_dt(after.timed_out_until, "R"), inline=True)
            else:
                embed = discord.Embed(
                    title="✅ Timeout Removed",
                    description=f"The timeout of {after.mention} was removed.",
                    color=COLOR_GOOD,
                )
            embed.set_thumbnail(url=after.display_avatar.url)
            embed.add_field(name="Member", value=who(after), inline=True)
            self.add_actor(embed, entry)
            await self.log(guild, "timeout", embed)

    # ---------------------------------------------------------------- roles created / deleted
    @commands.Cog.listener()
    async def on_guild_role_create(self, role: discord.Role):
        if role.guild.id != GUILD_ID:
            return
        entry = await self.audit_entry(role.guild, discord.AuditLogAction.role_create, role.id)
        embed = discord.Embed(title="🆕 Role Created", description=f"{role.mention}", color=COLOR_GOOD)
        embed.add_field(name="Role", value=f"`{role.name}` (`{role.id}`)", inline=True)
        self.add_actor(embed, entry)
        await self.log(role.guild, "role_cd", embed)

    @commands.Cog.listener()
    async def on_guild_role_delete(self, role: discord.Role):
        if role.guild.id != GUILD_ID:
            return
        entry = await self.audit_entry(role.guild, discord.AuditLogAction.role_delete, role.id)
        embed = discord.Embed(title="🗑️ Role Deleted", description=f"`{role.name}`", color=COLOR_BAD)
        embed.add_field(name="Role", value=f"`{role.name}` (`{role.id}`)", inline=True)
        self.add_actor(embed, entry)
        await self.log(role.guild, "role_cd", embed)

    # ---------------------------------------------------------------- channels created / deleted
    @commands.Cog.listener()
    async def on_guild_channel_create(self, channel: discord.abc.GuildChannel):
        if channel.guild.id != GUILD_ID:
            return
        entry = await self.audit_entry(channel.guild, discord.AuditLogAction.channel_create, channel.id)
        embed = discord.Embed(title="🆕 Channel Created", description=f"{channel.mention}", color=COLOR_GOOD)
        embed.add_field(name="Channel", value=f"`{channel.name}` (`{channel.id}`)", inline=True)
        embed.add_field(name="Type", value=f"`{str(channel.type).replace('_', ' ')}`", inline=True)
        self.add_actor(embed, entry)
        await self.log(channel.guild, "channel_cd", embed)

    @commands.Cog.listener()
    async def on_guild_channel_delete(self, channel: discord.abc.GuildChannel):
        if channel.guild.id != GUILD_ID:
            return
        entry = await self.audit_entry(channel.guild, discord.AuditLogAction.channel_delete, channel.id)
        embed = discord.Embed(title="🗑️ Channel Deleted", description=f"`{channel.name}`", color=COLOR_BAD)
        embed.add_field(name="Channel", value=f"`{channel.name}` (`{channel.id}`)", inline=True)
        embed.add_field(name="Type", value=f"`{str(channel.type).replace('_', ' ')}`", inline=True)
        self.add_actor(embed, entry)
        await self.log(channel.guild, "channel_cd", embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(ServerLogs(bot))
    print("✅ Server logs loaded")
