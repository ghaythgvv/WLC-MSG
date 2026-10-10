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
    voice mod mute / deafen / disconnect -desconect-deafen-mute
    everything .............. LOGS-ALL-SERVER

Channels are found automatically by their NAME (the symbols in front don't matter).
If you ever rename a channel, either keep the keyword in the name or paste its ID in
LOG_CHANNEL_IDS below.

The bot needs: View Audit Log (to show WHO did it) + View Channel / Send Messages / Embed Links
in each log channel. SERVER MEMBERS INTENT must be on (it already is for the welcome bot).

This file is loaded by welcome_bot.py:  await bot.load_extension("server_logs")

Fixed in this version
    - Voice logs no longer show "# unknown": when the voice channel was deleted in the meantime
      (temporary / report rooms), the channel NAME is shown instead.
    - "Disconnected By Moderator" is only logged when the audit log really shows a NEW disconnect.
      Before, someone leaving on their own right after a moderator disconnected another person
      was blamed on that moderator.
    - Server mute / deafen and timeout logs now check that the audit entry really is a mute / deafen /
      timeout, so a nickname change or other edit can't be shown as the "moderator" of a mute.
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
    "voice_state": "desconect-deafen-mute",
    "all": "logs-all-server",
}

# Optional: force a channel by ID instead of by name. Example: {"kick": 123456789}
LOG_CHANNEL_IDS: dict[str, int | None] = {}

PURPLE = 0x9B30FF   # every log uses this color
NEW_ACCOUNT_DAYS = 7
# ================================================================


def norm(text: str) -> str:
    """Fancy letters, emoji and symbols are ignored: '┃𝗥𝗢𝗟𝗘-𝗚𝗜𝗩𝗘𝗡' -> 'rolegiven'."""
    text = unicodedata.normalize("NFKC", text).lower()
    return "".join(c for c in text if c.isalnum())


def person(user: discord.abc.Snowflake | None) -> str:
    """@mention + copyable ID on one line."""
    if user is None:
        return "Unknown"
    mention = getattr(user, "mention", f"<@{user.id}>")
    return f"{mention} (`{user.id}`)"


def when(dt) -> str:
    """'Oct 5, 2026 (3 hours ago)'"""
    if dt is None:
        return "Unknown"
    return f"{discord.utils.format_dt(dt, 'D')} ({discord.utils.format_dt(dt, 'R')})"


def span(seconds: float) -> str:
    """Seconds -> '2d 3h'."""
    seconds = int(max(seconds, 0))
    parts = []
    for name, size in (("d", 86400), ("h", 3600), ("m", 60), ("s", 1)):
        if seconds >= size:
            parts.append(f"{seconds // size}{name}")
            seconds %= size
        if len(parts) == 2:
            break
    return " ".join(parts) or "0s"


def make(title: str, *lines: str) -> discord.Embed:
    """Big # title, then one clean line per detail."""
    body = "\n".join(line for line in lines if line)
    return discord.Embed(description=f"# {title}\n{body}", color=PURPLE)


def line(label: str, value: str) -> str:
    return f"**{label}:** {value}"


def chan_type(channel: discord.abc.GuildChannel) -> str:
    return channel.type.name.replace("_", " ").title()


def yn(value: bool) -> str:
    return "Yes" if value else "No"


def vc_ref(guild: discord.Guild, channel) -> str:
    """A clickable voice channel - or, if it was deleted meanwhile (temporary / report rooms),
    its name instead of '# unknown'."""
    live = guild.get_channel(channel.id)
    if live is not None:
        return f"{live.mention} (`{live.id}`)"
    return f"**{channel.name}** (`{channel.id}`) - channel was deleted"


class ServerLogs(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        # audit entry id -> how many of its disconnects were already matched to a member
        self._disconnects_used: dict[int, int] = {}

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
            print("[logs] ERROR: server not found")
            return
        for key in CHANNEL_KEYWORDS:
            ch = self.find_channel(guild, key)
            if ch is None:
                print(f"[logs] ERROR: no channel found for '{key}' (looking for '{CHANNEL_KEYWORDS[key]}')")
                continue
            perms = ch.permissions_for(guild.me)
            ok = perms.view_channel and perms.send_messages and perms.embed_links
            print(f"[logs] {'OK' if ok else 'WARN'}: {key} -> #{ch.name}" + ("" if ok else "  (bot can't send/embed here)"))
        if not guild.me.guild_permissions.view_audit_log:
            print("[logs] WARN: the bot is missing View Audit Log")

    async def log(self, guild: discord.Guild, key: str, embed: discord.Embed) -> None:
        """Send the embed to its own channel and to LOGS-ALL-SERVER."""
        embed.timestamp = discord.utils.utcnow()
        embed.set_footer(text="ELT Logs")
        sent_to: set[int] = set()
        for k in (key, "all"):
            ch = self.find_channel(guild, k)
            if ch is None or ch.id in sent_to:
                continue
            sent_to.add(ch.id)
            try:
                await ch.send(embed=embed, allowed_mentions=discord.AllowedMentions.none())
            except discord.HTTPException as e:
                print(f"[logs] ERROR: could not log to #{ch.name}: {e}")

    async def audit_entry(
        self,
        guild: discord.Guild,
        action: discord.AuditLogAction,
        target_id: int,
        within: float = 20.0,
        check=None,
    ) -> discord.AuditLogEntry | None:
        """Finds the audit log entry for an action that just happened (to show who did it).
        `check(entry)` can reject entries that are the right type but the wrong kind of change."""
        if not guild.me.guild_permissions.view_audit_log:
            return None
        await asyncio.sleep(2)  # Discord writes the audit log entry slightly after the event
        try:
            async for entry in guild.audit_logs(limit=15, action=action):
                if entry.target is None or entry.target.id != target_id:
                    continue
                if check is not None and not check(entry):
                    continue
                age = (discord.utils.utcnow() - entry.created_at).total_seconds()
                if age <= within:
                    return entry
        except discord.HTTPException:
            pass
        return None

    @staticmethod
    def by(entry: discord.AuditLogEntry | None, label: str = "By") -> str:
        return line(label, person(entry.user) if entry else "Unknown")

    @staticmethod
    def why(entry: discord.AuditLogEntry | None, always: bool = False) -> str:
        """Reason line. Always shown for punishments, only when it exists otherwise."""
        text = entry.reason if entry and entry.reason else None
        if text:
            return line("Reason", text[:900])
        return line("Reason", "No reason provided") if always else ""

    # ---------------------------------------------------------------- join / leave
    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        if member.guild.id != GUILD_ID:
            return
        age = (discord.utils.utcnow() - member.created_at).total_seconds()
        embed = make(
            "Member Joined",
            line("Member", person(member)),
            line("Account", "Bot" if member.bot else "User"),
            line("Created", when(member.created_at)),
            line("Members", f"`{member.guild.member_count:,}`"),
            f"**New account** - only `{span(age)}` old." if age < NEW_ACCOUNT_DAYS * 86400 else "",
        )
        embed.set_thumbnail(url=member.display_avatar.url)
        await self.log(member.guild, "join_leave", embed)

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member):
        guild = member.guild
        if guild.id != GUILD_ID:
            return

        roles = [r.mention for r in reversed(member.roles) if r != guild.default_role]
        stayed = (discord.utils.utcnow() - member.joined_at).total_seconds() if member.joined_at else None
        embed = make(
            "Member Left",
            line("Member", person(member)),
            line("Time in server", f"`{span(stayed)}`") if stayed is not None else "",
            line("Joined", when(member.joined_at)) if member.joined_at else "",
            line("Members", f"`{guild.member_count:,}`"),
            line(f"Roles ({len(roles)})", " ".join(roles)[:900] if roles else "None"),
        )
        embed.set_thumbnail(url=member.display_avatar.url)
        await self.log(guild, "join_leave", embed)

        # Was it a kick?
        entry = await self.audit_entry(guild, discord.AuditLogAction.kick, member.id)
        if entry:
            kick = make(
                "Member Kicked",
                line("Member", person(member)),
                self.by(entry, "Moderator"),
                self.why(entry, always=True),
            )
            kick.set_thumbnail(url=member.display_avatar.url)
            await self.log(guild, "kick", kick)

    # ---------------------------------------------------------------- bans
    @commands.Cog.listener()
    async def on_member_ban(self, guild: discord.Guild, user: discord.User):
        if guild.id != GUILD_ID:
            return
        entry = await self.audit_entry(guild, discord.AuditLogAction.ban, user.id)
        embed = make(
            "Member Banned",
            line("Member", person(user)),
            self.by(entry, "Moderator"),
            line("Created", when(user.created_at)),
            self.why(entry, always=True),
        )
        embed.set_thumbnail(url=user.display_avatar.url)
        await self.log(guild, "ban", embed)

    @commands.Cog.listener()
    async def on_member_unban(self, guild: discord.Guild, user: discord.User):
        if guild.id != GUILD_ID:
            return
        entry = await self.audit_entry(guild, discord.AuditLogAction.unban, user.id)
        embed = make(
            "Member Unbanned",
            line("Member", person(user)),
            self.by(entry, "Moderator"),
            self.why(entry),
        )
        embed.set_thumbnail(url=user.display_avatar.url)
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
            elif removed and not added:
                title = "Role Removed"
            else:
                title = "Roles Updated"
            embed = make(
                title,
                line("Member", person(after)),
                self.by(entry, "Moderator"),
                line("Added", " ".join(r.mention for r in added)[:900]) if added else "",
                line("Removed", " ".join(r.mention for r in removed)[:900]) if removed else "",
                self.why(entry),
            )
            embed.set_thumbnail(url=after.display_avatar.url)
            await self.log(guild, "role_member", embed)

        # --- timeout / untimeout
        if before.timed_out_until != after.timed_out_until:
            entry = await self.audit_entry(
                guild, discord.AuditLogAction.member_update, after.id,
                check=lambda e: getattr(e.before, "timed_out_until", None) is not None
                or getattr(e.after, "timed_out_until", None) is not None,
            )
            now = discord.utils.utcnow()
            if after.timed_out_until and after.timed_out_until > now:
                embed = make(
                    "Member Timed Out",
                    line("Member", person(after)),
                    self.by(entry, "Moderator"),
                    line("Duration", f"`{span((after.timed_out_until - now).total_seconds())}`"),
                    line("Ends", discord.utils.format_dt(after.timed_out_until, "F")),
                    self.why(entry, always=True),
                )
            else:
                embed = make(
                    "Timeout Removed",
                    line("Member", person(after)),
                    self.by(entry, "Moderator"),
                    self.why(entry),
                )
            embed.set_thumbnail(url=after.display_avatar.url)
            await self.log(guild, "timeout", embed)

    # ---------------------------------------------------------------- roles created / deleted
    @staticmethod
    def role_lines(role: discord.Role) -> list[str]:
        return [
            line("Role", f"{role.name} (`{role.id}`)"),
            line("Color", f"`{str(role.color).upper()}`"),
            line("Position", f"`{role.position}`"),
            line("Hoisted", yn(role.hoist)),
            line("Mentionable", yn(role.mentionable)),
            line("Administrator", yn(role.permissions.administrator)),
        ]

    @commands.Cog.listener()
    async def on_guild_role_create(self, role: discord.Role):
        if role.guild.id != GUILD_ID:
            return
        entry = await self.audit_entry(role.guild, discord.AuditLogAction.role_create, role.id)
        embed = make("Role Created", *self.role_lines(role), self.by(entry, "Created by"))
        await self.log(role.guild, "role_cd", embed)

    @commands.Cog.listener()
    async def on_guild_role_delete(self, role: discord.Role):
        if role.guild.id != GUILD_ID:
            return
        entry = await self.audit_entry(role.guild, discord.AuditLogAction.role_delete, role.id)
        embed = make("Role Deleted", *self.role_lines(role), self.by(entry, "Deleted by"))
        await self.log(role.guild, "role_cd", embed)

    # ---------------------------------------------------------------- channels created / deleted
    @staticmethod
    def channel_lines(channel: discord.abc.GuildChannel) -> list[str]:
        category = getattr(channel, "category", None)
        lines = [
            line("Channel", f"{channel.name} (`{channel.id}`)"),
            line("Type", chan_type(channel)),
            line("Category", category.name if category else "None"),
        ]
        topic = getattr(channel, "topic", None)
        if topic:
            lines.append(line("Topic", topic[:300]))
        if getattr(channel, "nsfw", False):
            lines.append(line("Age-restricted", "Yes"))
        limit = getattr(channel, "user_limit", None)
        if limit:
            lines.append(line("User limit", f"`{limit}`"))
        return lines

    @commands.Cog.listener()
    async def on_guild_channel_create(self, channel: discord.abc.GuildChannel):
        if channel.guild.id != GUILD_ID:
            return
        entry = await self.audit_entry(channel.guild, discord.AuditLogAction.channel_create, channel.id)
        embed = make("Channel Created", *self.channel_lines(channel), self.by(entry, "Created by"))
        await self.log(channel.guild, "channel_cd", embed)

    @commands.Cog.listener()
    async def on_guild_channel_delete(self, channel: discord.abc.GuildChannel):
        if channel.guild.id != GUILD_ID:
            return
        entry = await self.audit_entry(channel.guild, discord.AuditLogAction.channel_delete, channel.id)
        embed = make("Channel Deleted", *self.channel_lines(channel), self.by(entry, "Deleted by"))
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
            embed = make(
                "Joined Voice Channel",
                line("Member", person(member)),
                line("Channel", vc_ref(guild, after.channel)),
            )
        elif before.channel is not None and after.channel is None:
            embed = make(
                "Left Voice Channel",
                line("Member", person(member)),
                line("Channel", vc_ref(guild, before.channel)),
            )
        else:
            embed = make(
                "Moved Voice Channel",
                line("Member", person(member)),
                line("From", vc_ref(guild, before.channel)),
                line("To", vc_ref(guild, after.channel)),
            )

        embed.set_thumbnail(url=member.display_avatar.url)
        await self.log(guild, "voice", embed)

    # ---------------------------------------------------------------- voice power abuse (moderator actions only)
    async def _disconnect_entry(self, guild: discord.Guild, member: discord.Member) -> discord.AuditLogEntry | None:
        """Returns the audit entry of a moderator disconnect that has NOT been matched to a member yet.
        Discord writes ONE entry per disconnect action and raises its `count` when the same moderator
        disconnects more people shortly after - so every leave 'uses up' one count. A person who simply
        leaves on their own finds no unused count and is correctly ignored."""
        if not guild.me.guild_permissions.view_audit_log:
            return None
        await asyncio.sleep(2)
        try:
            async for entry in guild.audit_logs(limit=8, action=discord.AuditLogAction.member_disconnect):
                age = (discord.utils.utcnow() - entry.created_at).total_seconds()
                if age > 15 or entry.user is None or entry.user.id == member.id:
                    continue
                count = int(getattr(entry.extra, "count", 1) or 1)
                used = self._disconnects_used.get(entry.id, 0)
                if used < count:
                    self._disconnects_used[entry.id] = used + 1
                    if len(self._disconnects_used) > 200:   # keep the memory small
                        for old in sorted(self._disconnects_used)[:100]:
                            self._disconnects_used.pop(old, None)
                    return entry
        except discord.HTTPException:
            pass
        return None

    @commands.Cog.listener("on_voice_state_update")
    async def voice_mute_deafen(
        self, member: discord.Member, before: discord.VoiceState, after: discord.VoiceState
    ):
        guild = member.guild
        if guild.id != GUILD_ID:
            return

        # --- server mute / deafen (only logged if a moderator did it)
        events = []
        if after.channel is not None:
            if before.mute != after.mute:
                events.append(("Server Muted" if after.mute else "Server Unmuted", "mute"))
            if before.deaf != after.deaf:
                events.append(("Server Deafened" if after.deaf else "Server Undeafened", "deaf"))
        for title, attr in events:
            entry = await self.audit_entry(
                guild, discord.AuditLogAction.member_update, member.id,
                check=lambda e, a=attr: getattr(e.after, a, None) is not None,
            )
            if entry is None or entry.user.id == member.id:
                continue
            embed = make(
                title,
                line("Member", person(member)),
                line("Channel", vc_ref(guild, after.channel)),
                self.by(entry, "Moderator"),
            )
            embed.set_thumbnail(url=member.display_avatar.url)
            await self.log(guild, "voice_state", embed)

        # --- disconnected from voice by a moderator
        if before.channel is not None and after.channel is None:
            entry = await self._disconnect_entry(guild, member)
            if entry is not None:
                embed = make(
                    "Disconnected By Moderator",
                    line("Member", person(member)),
                    line("Channel", vc_ref(guild, before.channel)),
                    self.by(entry, "Moderator"),
                )
                embed.set_thumbnail(url=member.display_avatar.url)
                await self.log(guild, "voice_state", embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(ServerLogs(bot))
    print("[logs] Server logs loaded")
