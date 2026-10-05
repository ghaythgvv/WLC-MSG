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

# ONE color for every log: purple
PURPLE = 0x9B30FF

# Purple-only emoji set
E = {
    "join": "💜",
    "leave": "🟣",
    "ban": "🔮",
    "unban": "🟪",
    "kick": "👿",
    "timeout": "😈",
    "untimeout": "🪻",
    "role": "💜",
    "role_add": "🟣",
    "role_remove": "🟪",
    "role_new": "🔮",
    "role_del": "👿",
    "chan_new": "🪻",
    "chan_del": "😈",
    "dot": "🟣",
}

CHANNEL_ICONS = {
    "text": "💬",
    "voice": "🔊",
    "category": "📁",
    "stage_voice": "🎙️",
    "forum": "🗂️",
    "news": "📢",
}
# ================================================================


def norm(text: str) -> str:
    """Fancy letters (𝗥𝗢𝗟𝗘), emoji and symbols are ignored: '┃𝗥𝗢𝗟𝗘-𝗚𝗜𝗩𝗘𝗡' -> 'rolegiven'."""
    text = unicodedata.normalize("NFKC", text).lower()
    return "".join(c for c in text if c.isalnum())


def who(user: discord.abc.Snowflake | None) -> str:
    if user is None:
        return "`Unknown`"
    mention = getattr(user, "mention", f"<@{user.id}>")
    return f"{mention}\n`{user.id}`"


def ts(dt) -> str:
    """Full date + relative time, e.g.  'October 5, 2026 3:20 PM (2 hours ago)'."""
    if dt is None:
        return "`Unknown`"
    return f"{discord.utils.format_dt(dt, 'F')}\n({discord.utils.format_dt(dt, 'R')})"


def human_delta(seconds: float) -> str:
    seconds = int(seconds)
    parts = []
    for name, size in (("d", 86400), ("h", 3600), ("m", 60), ("s", 1)):
        if seconds >= size:
            parts.append(f"{seconds // size}{name}")
            seconds %= size
    return " ".join(parts) or "0s"


def make(title: str, description: str | None = None) -> discord.Embed:
    return discord.Embed(title=title, description=description, color=PURPLE)


def ctype(channel: discord.abc.GuildChannel) -> str:
    name = str(channel.type).replace("channel_type.", "").replace("_", " ")
    icon = CHANNEL_ICONS.get(str(channel.type).replace("channel_type.", ""), "📌")
    return f"{icon} {name.title()}"


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
        embed.set_footer(text="ELT Logs • 💜", icon_url=guild.icon.url if guild.icon else None)
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
    def add_actor(embed: discord.Embed, entry: discord.AuditLogEntry | None, label: str = "Done By") -> None:
        embed.add_field(name=f"{E['dot']} {label}", value=who(entry.user) if entry else "`Unknown`", inline=True)
        reason = entry.reason if entry and entry.reason else None
        embed.add_field(name=f"{E['dot']} Reason", value=f"```{reason[:900]}```" if reason else "```No reason given```", inline=False)

    @staticmethod
    def user_header(embed: discord.Embed, user: discord.abc.User) -> None:
        embed.set_author(name=f"{user} • {user.id}", icon_url=user.display_avatar.url)
        embed.set_thumbnail(url=user.display_avatar.url)

    # ---------------------------------------------------------------- join / leave
    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        if member.guild.id != GUILD_ID:
            return
        age = (discord.utils.utcnow() - member.created_at).total_seconds()
        embed = make(f"{E['join']} Member Joined", f"{member.mention} just joined **{member.guild.name}** — welcome! 💜")
        self.user_header(embed, member)
        embed.add_field(name=f"{E['dot']} Member", value=who(member), inline=True)
        embed.add_field(name=f"{E['dot']} Member #", value=f"`{member.guild.member_count:,}`", inline=True)
        embed.add_field(name=f"{E['dot']} Type", value="`Bot`" if member.bot else "`Human`", inline=True)
        embed.add_field(name=f"{E['dot']} Account Created", value=ts(member.created_at), inline=False)
        embed.add_field(name=f"{E['dot']} Account Age", value=f"`{human_delta(age)}`", inline=True)
        if age < 7 * 86400:
            embed.add_field(name=f"{E['dot']} Warning", value="`New account (under 7 days old)`", inline=True)
        await self.log(member.guild, "join_leave", embed)

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member):
        guild = member.guild
        if guild.id != GUILD_ID:
            return

        embed = make(f"{E['leave']} Member Left", f"{member.mention} left **{guild.name}**.")
        self.user_header(embed, member)
        embed.add_field(name=f"{E['dot']} Member", value=who(member), inline=True)
        embed.add_field(name=f"{E['dot']} Members Now", value=f"`{guild.member_count:,}`", inline=True)
        if member.joined_at:
            stayed = (discord.utils.utcnow() - member.joined_at).total_seconds()
            embed.add_field(name=f"{E['dot']} Time In Server", value=f"`{human_delta(stayed)}`", inline=True)
            embed.add_field(name=f"{E['dot']} Joined", value=ts(member.joined_at), inline=False)
        roles = [r.mention for r in reversed(member.roles) if r != guild.default_role]
        embed.add_field(
            name=f"{E['dot']} Roles ({len(roles)})",
            value=(" ".join(roles)[:1000] if roles else "`No roles`"),
            inline=False,
        )
        await self.log(guild, "join_leave", embed)

        # Was it a kick?
        entry = await self.audit_entry(guild, discord.AuditLogAction.kick, member.id)
        if entry:
            kick = make(f"{E['kick']} Member Kicked", f"{member.mention} was kicked from **{guild.name}**.")
            self.user_header(kick, member)
            kick.add_field(name=f"{E['dot']} Member", value=who(member), inline=True)
            self.add_actor(kick, entry, "Kicked By")
            await self.log(guild, "kick", kick)

    # ---------------------------------------------------------------- bans
    @commands.Cog.listener()
    async def on_member_ban(self, guild: discord.Guild, user: discord.User):
        if guild.id != GUILD_ID:
            return
        entry = await self.audit_entry(guild, discord.AuditLogAction.ban, user.id)
        embed = make(f"{E['ban']} Member Banned", f"{user.mention} was banned from **{guild.name}**.")
        self.user_header(embed, user)
        embed.add_field(name=f"{E['dot']} Member", value=who(user), inline=True)
        embed.add_field(name=f"{E['dot']} Account Created", value=ts(user.created_at), inline=True)
        self.add_actor(embed, entry, "Banned By")
        await self.log(guild, "ban", embed)

    @commands.Cog.listener()
    async def on_member_unban(self, guild: discord.Guild, user: discord.User):
        if guild.id != GUILD_ID:
            return
        entry = await self.audit_entry(guild, discord.AuditLogAction.unban, user.id)
        embed = make(f"{E['unban']} Member Unbanned", f"{user.mention} was unbanned from **{guild.name}**.")
        self.user_header(embed, user)
        embed.add_field(name=f"{E['dot']} Member", value=who(user), inline=True)
        self.add_actor(embed, entry, "Unbanned By")
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
            if added and not removed:
                title, icon = "Role Given", E["role_add"]
            elif removed and not added:
                title, icon = "Role Removed", E["role_remove"]
            else:
                title, icon = "Roles Updated", E["role"]
            embed = make(f"{icon} {title}", f"Roles changed for {after.mention}.")
            self.user_header(embed, after)
            embed.add_field(name=f"{E['dot']} Member", value=who(after), inline=True)
            self.add_actor(embed, entry, "Changed By")
            if added:
                embed.add_field(name=f"{E['role_add']} Added", value=" ".join(r.mention for r in added)[:1000], inline=False)
            if removed:
                embed.add_field(name=f"{E['role_remove']} Removed", value=" ".join(r.mention for r in removed)[:1000], inline=False)
            current = [r.mention for r in reversed(after.roles) if r != guild.default_role]
            embed.add_field(
                name=f"{E['dot']} Current Roles ({len(current)})",
                value=(" ".join(current)[:1000] if current else "`No roles`"),
                inline=False,
            )
            await self.log(guild, "role_member", embed)

        # --- timeout / untimeout
        if before.timed_out_until != after.timed_out_until:
            entry = await self.audit_entry(guild, discord.AuditLogAction.member_update, after.id)
            now = discord.utils.utcnow()
            if after.timed_out_until and after.timed_out_until > now:
                embed = make(f"{E['timeout']} Member Timed Out", f"{after.mention} was timed out.")
                duration = (after.timed_out_until - now).total_seconds()
                embed.add_field(name=f"{E['dot']} Duration", value=f"`~{human_delta(duration)}`", inline=True)
                embed.add_field(name=f"{E['dot']} Ends", value=ts(after.timed_out_until), inline=False)
                by_label = "Timed Out By"
            else:
                embed = make(f"{E['untimeout']} Timeout Removed", f"The timeout of {after.mention} was removed.")
                by_label = "Removed By"
            self.user_header(embed, after)
            embed.insert_field_at(0, name=f"{E['dot']} Member", value=who(after), inline=True)
            self.add_actor(embed, entry, by_label)
            await self.log(guild, "timeout", embed)

    # ---------------------------------------------------------------- roles created / deleted
    @staticmethod
    def role_info(embed: discord.Embed, role: discord.Role) -> None:
        embed.add_field(name=f"{E['dot']} Role", value=f"`{role.name}`\n`{role.id}`", inline=True)
        embed.add_field(name=f"{E['dot']} Color", value=f"`{str(role.color).upper()}`", inline=True)
        embed.add_field(name=f"{E['dot']} Position", value=f"`{role.position}`", inline=True)
        embed.add_field(name=f"{E['dot']} Hoisted", value="`Yes`" if role.hoist else "`No`", inline=True)
        embed.add_field(name=f"{E['dot']} Mentionable", value="`Yes`" if role.mentionable else "`No`", inline=True)
        embed.add_field(
            name=f"{E['dot']} Administrator",
            value="`Yes ⚠️`" if role.permissions.administrator else "`No`",
            inline=True,
        )

    @commands.Cog.listener()
    async def on_guild_role_create(self, role: discord.Role):
        if role.guild.id != GUILD_ID:
            return
        entry = await self.audit_entry(role.guild, discord.AuditLogAction.role_create, role.id)
        embed = make(f"{E['role_new']} Role Created", f"{role.mention} was created.")
        self.role_info(embed, role)
        self.add_actor(embed, entry, "Created By")
        await self.log(role.guild, "role_cd", embed)

    @commands.Cog.listener()
    async def on_guild_role_delete(self, role: discord.Role):
        if role.guild.id != GUILD_ID:
            return
        entry = await self.audit_entry(role.guild, discord.AuditLogAction.role_delete, role.id)
        embed = make(f"{E['role_del']} Role Deleted", f"`{role.name}` was deleted.")
        self.role_info(embed, role)
        self.add_actor(embed, entry, "Deleted By")
        await self.log(role.guild, "role_cd", embed)

    # ---------------------------------------------------------------- channels created / deleted
    @staticmethod
    def channel_info(embed: discord.Embed, channel: discord.abc.GuildChannel) -> None:
        embed.add_field(name=f"{E['dot']} Channel", value=f"`{channel.name}`\n`{channel.id}`", inline=True)
        embed.add_field(name=f"{E['dot']} Type", value=ctype(channel), inline=True)
        category = getattr(channel, "category", None)
        embed.add_field(name=f"{E['dot']} Category", value=f"`{category.name}`" if category else "`None`", inline=True)
        topic = getattr(channel, "topic", None)
        if topic:
            embed.add_field(name=f"{E['dot']} Topic", value=f"```{topic[:300]}```", inline=False)
        if getattr(channel, "nsfw", False):
            embed.add_field(name=f"{E['dot']} NSFW", value="`Yes`", inline=True)
        limit = getattr(channel, "user_limit", None)
        if limit:
            embed.add_field(name=f"{E['dot']} User Limit", value=f"`{limit}`", inline=True)

    @commands.Cog.listener()
    async def on_guild_channel_create(self, channel: discord.abc.GuildChannel):
        if channel.guild.id != GUILD_ID:
            return
        entry = await self.audit_entry(channel.guild, discord.AuditLogAction.channel_create, channel.id)
        embed = make(f"{E['chan_new']} Channel Created", f"{channel.mention} was created.")
        self.channel_info(embed, channel)
        self.add_actor(embed, entry, "Created By")
        await self.log(channel.guild, "channel_cd", embed)

    @commands.Cog.listener()
    async def on_guild_channel_delete(self, channel: discord.abc.GuildChannel):
        if channel.guild.id != GUILD_ID:
            return
        entry = await self.audit_entry(channel.guild, discord.AuditLogAction.channel_delete, channel.id)
        embed = make(f"{E['chan_del']} Channel Deleted", f"`#{channel.name}` was deleted.")
        self.channel_info(embed, channel)
        self.add_actor(embed, entry, "Deleted By")
        await self.log(channel.guild, "channel_cd", embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(ServerLogs(bot))
    print("✅ Server logs loaded")
