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
    voice join / leave / move -join-left-the-channel
    everything .............. LOGS-ALL-SERVER

Channels are found automatically by their NAME (the emoji / symbols in front don't matter).
If you ever rename a channel, either keep the keyword in the name or paste its ID in
LOG_CHANNEL_IDS below.

The bot needs: View Audit Log (to show WHO did it) + View Channel / Send Messages / Embed Links
in each log channel. SERVER MEMBERS INTENT must be on (it already is for the welcome bot).
Voice logs also need the voice_states intent (included in Intents.default()).

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
    "voice": "join-left-the-channel",
    "all": "logs-all-server",
}

# Optional: force a channel by ID instead of by name. Example: {"kick": 123456789}
LOG_CHANNEL_IDS: dict[str, int | None] = {}

PURPLE = 0x9B30FF   # every log uses this color
MARK = "🟣"          # the ONLY emoji used (one per title)
NEW_ACCOUNT_DAYS = 7
# ================================================================


def norm(text: str) -> str:
    """Fancy letters (𝗥𝗢𝗟𝗘), emoji and symbols are ignored: '┃𝗥𝗢𝗟𝗘-𝗚𝗜𝗩𝗘𝗡' -> 'rolegiven'."""
    text = unicodedata.normalize("NFKC", text).lower()
    return "".join(c for c in text if c.isalnum())


def person(user: discord.abc.Snowflake | None) -> str:
    """@mention on the first line, copyable ID on the second."""
    if user is None:
        return "Unknown"
    mention = getattr(user, "mention", f"<@{user.id}>")
    return f"{mention}\n`{user.id}`"


def when(dt) -> str:
    """'Oct 5, 2026 (3 hours ago)'"""
    if dt is None:
        return "Unknown"
    return f"{discord.utils.format_dt(dt, 'D')} ({discord.utils.format_dt(dt, 'R')})"


def span(seconds: float) -> str:
    """Seconds -> '2d 3h 10m'."""
    seconds = int(max(seconds, 0))
    parts = []
    for name, size in (("d", 86400), ("h", 3600), ("m", 60), ("s", 1)):
        if seconds >= size:
            parts.append(f"{seconds // size}{name}")
            seconds %= size
        if len(parts) == 2:
            break
    return " ".join(parts) or "0s"


def make(title: str, description: str) -> discord.Embed:
    return discord.Embed(title=f"{MARK}  {title}", description=description, color=PURPLE)


def chan_type(channel: discord.abc.GuildChannel) -> str:
    return channel.type.name.replace("_", " ").title()


def yn(value: bool) -> str:
    return "Yes" if value else "No"


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
    def actor(embed: discord.Embed, entry: discord.AuditLogEntry | None, label: str = "Moderator") -> None:
        embed.add_field(name=label, value=person(entry.user) if entry else "Unknown", inline=True)

    @staticmethod
    def reason(embed: discord.Embed, entry: discord.AuditLogEntry | None, always: bool = False) -> None:
        """Reason block. Always shown for punishments, only when it exists otherwise."""
        text = entry.reason if entry and entry.reason else None
        if text:
            embed.add_field(name="Reason", value=f">>> {text[:900]}", inline=False)
        elif always:
            embed.add_field(name="Reason", value="> No reason provided", inline=False)

    # ---------------------------------------------------------------- join / leave
    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        if member.guild.id != GUILD_ID:
            return
        age = (discord.utils.utcnow() - member.created_at).total_seconds()
        embed = make("Member Joined", f"{member.mention} joined the server.")
        embed.set_thumbnail(url=member.display_avatar.url)
        embed.add_field(name="Member", value=person(member), inline=True)
        embed.add_field(name="Member Count", value=f"{member.guild.member_count:,}", inline=True)
        embed.add_field(name="Account Type", value="Bot" if member.bot else "User", inline=True)
        embed.add_field(name="Account Created", value=when(member.created_at), inline=False)
        if age < NEW_ACCOUNT_DAYS * 86400:
            embed.add_field(
                name="Notice",
                value=f"**New account** — only {span(age)} old.",
                inline=False,
            )
        await self.log(member.guild, "join_leave", embed)

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member):
        guild = member.guild
        if guild.id != GUILD_ID:
            return

        embed = make("Member Left", f"{member.mention} left the server.")
        embed.set_thumbnail(url=member.display_avatar.url)
        embed.add_field(name="Member", value=person(member), inline=True)
        embed.add_field(name="Member Count", value=f"{guild.member_count:,}", inline=True)
        if member.joined_at:
            stayed = (discord.utils.utcnow() - member.joined_at).total_seconds()
            embed.add_field(name="Time In Server", value=span(stayed), inline=True)
            embed.add_field(name="Joined", value=when(member.joined_at), inline=False)
        roles = [r.mention for r in reversed(member.roles) if r != guild.default_role]
        embed.add_field(
            name=f"Roles ({len(roles)})",
            value=" ".join(roles)[:1000] if roles else "None",
            inline=False,
        )
        await self.log(guild, "join_leave", embed)

        # Was it a kick?
        entry = await self.audit_entry(guild, discord.AuditLogAction.kick, member.id)
        if entry:
            kick = make("Member Kicked", f"{member.mention} was kicked from the server.")
            kick.set_thumbnail(url=member.display_avatar.url)
            kick.add_field(name="Member", value=person(member), inline=True)
            self.actor(kick, entry)
            self.reason(kick, entry, always=True)
            await self.log(guild, "kick", kick)

    # ---------------------------------------------------------------- bans
    @commands.Cog.listener()
    async def on_member_ban(self, guild: discord.Guild, user: discord.User):
        if guild.id != GUILD_ID:
            return
        entry = await self.audit_entry(guild, discord.AuditLogAction.ban, user.id)
        embed = make("Member Banned", f"{user.mention} was banned from the server.")
        embed.set_thumbnail(url=user.display_avatar.url)
        embed.add_field(name="Member", value=person(user), inline=True)
        self.actor(embed, entry)
        embed.add_field(name="Account Created", value=when(user.created_at), inline=False)
        self.reason(embed, entry, always=True)
        await self.log(guild, "ban", embed)

    @commands.Cog.listener()
    async def on_member_unban(self, guild: discord.Guild, user: discord.User):
        if guild.id != GUILD_ID:
            return
        entry = await self.audit_entry(guild, discord.AuditLogAction.unban, user.id)
        embed = make("Member Unbanned", f"{user.mention} was unbanned.")
        embed.set_thumbnail(url=user.display_avatar.url)
        embed.add_field(name="Member", value=person(user), inline=True)
        self.actor(embed, entry)
        self.reason(embed, entry)
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
                title = "Role Given"
                desc = f"{' '.join(r.mention for r in added)} was given to {after.mention}."
            elif removed and not added:
                title = "Role Removed"
                desc = f"{' '.join(r.mention for r in removed)} was removed from {after.mention}."
            else:
                title = "Roles Updated"
                desc = f"Roles were changed for {after.mention}."
            embed = make(title, desc)
            embed.set_thumbnail(url=after.display_avatar.url)
            embed.add_field(name="Member", value=person(after), inline=True)
            self.actor(embed, entry)
            if added:
                embed.add_field(name="Added", value=" ".join(r.mention for r in added)[:1000], inline=False)
            if removed:
                embed.add_field(name="Removed", value=" ".join(r.mention for r in removed)[:1000], inline=False)
            self.reason(embed, entry)
            embed.add_field(
                name="Total Roles",
                value=str(len([r for r in after.roles if r != guild.default_role])),
                inline=True,
            )
            await self.log(guild, "role_member", embed)

        # --- timeout / untimeout
        if before.timed_out_until != after.timed_out_until:
            entry = await self.audit_entry(guild, discord.AuditLogAction.member_update, after.id)
            now = discord.utils.utcnow()
            if after.timed_out_until and after.timed_out_until > now:
                embed = make("Member Timed Out", f"{after.mention} was timed out.")
                embed.set_thumbnail(url=after.display_avatar.url)
                embed.add_field(name="Member", value=person(after), inline=True)
                self.actor(embed, entry)
                embed.add_field(name="Duration", value=span((after.timed_out_until - now).total_seconds()), inline=True)
                embed.add_field(name="Ends", value=discord.utils.format_dt(after.timed_out_until, "F"), inline=False)
                self.reason(embed, entry, always=True)
            else:
                embed = make("Timeout Removed", f"The timeout of {after.mention} was removed.")
                embed.set_thumbnail(url=after.display_avatar.url)
                embed.add_field(name="Member", value=person(after), inline=True)
                self.actor(embed, entry)
                self.reason(embed, entry)
            await self.log(guild, "timeout", embed)

    # ---------------------------------------------------------------- roles created / deleted
    @staticmethod
    def role_fields(embed: discord.Embed, role: discord.Role) -> None:
        embed.add_field(name="Role", value=f"{role.name}\n`{role.id}`", inline=True)
        embed.add_field(name="Color", value=f"`{str(role.color).upper()}`", inline=True)
        embed.add_field(name="Position", value=str(role.position), inline=True)
        flags = (
            f"Hoisted: **{yn(role.hoist)}**\n"
            f"Mentionable: **{yn(role.mentionable)}**\n"
            f"Administrator: **{yn(role.permissions.administrator)}**"
        )
        embed.add_field(name="Settings", value=flags, inline=False)

    @commands.Cog.listener()
    async def on_guild_role_create(self, role: discord.Role):
        if role.guild.id != GUILD_ID:
            return
        entry = await self.audit_entry(role.guild, discord.AuditLogAction.role_create, role.id)
        embed = make("Role Created", f"{role.mention} was created.")
        self.role_fields(embed, role)
        self.actor(embed, entry)
        await self.log(role.guild, "role_cd", embed)

    @commands.Cog.listener()
    async def on_guild_role_delete(self, role: discord.Role):
        if role.guild.id != GUILD_ID:
            return
        entry = await self.audit_entry(role.guild, discord.AuditLogAction.role_delete, role.id)
        embed = make("Role Deleted", f"**{role.name}** was deleted.")
        self.role_fields(embed, role)
        self.actor(embed, entry)
        await self.log(role.guild, "role_cd", embed)

    # ---------------------------------------------------------------- channels created / deleted
    @staticmethod
    def channel_fields(embed: discord.Embed, channel: discord.abc.GuildChannel) -> None:
        embed.add_field(name="Channel", value=f"{channel.name}\n`{channel.id}`", inline=True)
        embed.add_field(name="Type", value=chan_type(channel), inline=True)
        category = getattr(channel, "category", None)
        embed.add_field(name="Category", value=category.name if category else "None", inline=True)
        topic = getattr(channel, "topic", None)
        if topic:
            embed.add_field(name="Topic", value=f"> {topic[:300]}", inline=False)
        extras = []
        if getattr(channel, "nsfw", False):
            extras.append("Age-restricted: **Yes**")
        limit = getattr(channel, "user_limit", None)
        if limit:
            extras.append(f"User limit: **{limit}**")
        if extras:
            embed.add_field(name="Settings", value="\n".join(extras), inline=False)

    @commands.Cog.listener()
    async def on_guild_channel_create(self, channel: discord.abc.GuildChannel):
        if channel.guild.id != GUILD_ID:
            return
        entry = await self.audit_entry(channel.guild, discord.AuditLogAction.channel_create, channel.id)
        embed = make("Channel Created", f"{channel.mention} was created.")
        self.channel_fields(embed, channel)
        self.actor(embed, entry)
        await self.log(channel.guild, "channel_cd", embed)

    @commands.Cog.listener()
    async def on_guild_channel_delete(self, channel: discord.abc.GuildChannel):
        if channel.guild.id != GUILD_ID:
            return
        entry = await self.audit_entry(channel.guild, discord.AuditLogAction.channel_delete, channel.id)
        embed = make("Channel Deleted", f"**#{channel.name}** was deleted.")
        self.channel_fields(embed, channel)
        self.actor(embed, entry)
        await self.log(channel.guild, "channel_cd", embed)

    # ---------------------------------------------------------------- voice join / leave / move
    @commands.Cog.listener()
    async def on_voice_state_update(
        self, member: discord.Member, before: discord.VoiceState, after: discord.VoiceState
    ):
        guild = member.guild
        if guild.id != GUILD_ID or before.channel == after.channel:
            return

        if before.channel is None and after.channel is not None:
            embed = make("Joined Voice Channel", f"{member.mention} joined {after.channel.mention}.")
            embed.add_field(name="Channel", value=f"{after.channel.name}\n`{after.channel.id}`", inline=True)
        elif before.channel is not None and after.channel is None:
            embed = make("Left Voice Channel", f"{member.mention} left {before.channel.mention}.")
            embed.add_field(name="Channel", value=f"{before.channel.name}\n`{before.channel.id}`", inline=True)
        else:
            embed = make(
                "Moved Voice Channel",
                f"{member.mention} moved from {before.channel.mention} to {after.channel.mention}.",
            )
            embed.add_field(name="From", value=f"{before.channel.name}\n`{before.channel.id}`", inline=True)
            embed.add_field(name="To", value=f"{after.channel.name}\n`{after.channel.id}`", inline=True)

        embed.set_thumbnail(url=member.display_avatar.url)
        embed.insert_field_at(0, name="Member", value=person(member), inline=True)
        await self.log(guild, "voice", embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(ServerLogs(bot))
    print("✅ Server logs loaded")
