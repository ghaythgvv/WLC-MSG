"""
boost_cog.py  -  the boost card feature as a PLUG-IN for your existing ELITE SYSTEM bot.

It does NOT create a bot, does NOT sync commands and does NOT touch setup_hook / on_ready,
so it cannot remove or override your other commands (/warn, /ban, ...).

Files next to your main bot file:   boost_cog.py  +  boost_card.py   (+ optional fonts/ folder)

How to plug it in (in your main bot file, inside setup_hook, BEFORE the command sync):

    await bot.load_extension("boost_cog")

Then restart. /boosttest appears with your other commands on the next sync
(the next automatic sync, or mention the bot and type "sync" if your bot has that command).

Permissions in the BOOST channel: View Channel, Send Messages, Attach Files,
Read Message History, Manage Messages (to remove Discord's plain boost line).

Optional Railway variables:
    BOOST_CHANNEL_ID        post the cards in this channel instead of under the boost message
    DELETE_BOOST_MESSAGE    1 (default) = remove Discord's plain "just boosted" line, 0 = keep it
"""

import asyncio
import io
import os
import traceback
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

from boost_card import render_boost_card

# =========================== CONFIG ===========================
GUILD_ID = 1410440666747633707
GUILD = discord.Object(id=GUILD_ID)

BOOST_CHANNEL_ID = int(os.environ["BOOST_CHANNEL_ID"]) if os.environ.get("BOOST_CHANNEL_ID", "").isdigit() else None
DELETE_BOOST_MESSAGE = os.environ.get("DELETE_BOOST_MESSAGE", "1") == "1"

THANKS_TEXT = "💜 {mention} thank you for boosting **{server}**!"
LEVEL_UP_TEXT = "🎉 **{server}** just reached **Level {level}**!"
# ================================================================

BOOST_TYPES = {
    discord.MessageType.premium_guild_subscription: None,
    discord.MessageType.premium_guild_tier_1: 1,
    discord.MessageType.premium_guild_tier_2: 2,
    discord.MessageType.premium_guild_tier_3: 3,
}

_seen: set[int] = set()


async def make_card(member, guild: discord.Guild, boosts: int = 1, level_up: Optional[int] = None) -> bytes:
    try:
        avatar = await member.display_avatar.replace(size=256, format="png").read()
    except Exception as e:
        print(f"⚠️ [boost] Couldn't fetch avatar for {member}: {e}")
        avatar = None
    return await asyncio.to_thread(
        render_boost_card, member.display_name, guild.name, avatar,
        guild.premium_tier, guild.premium_subscription_count or 0, boosts, level_up,
    )


async def announce(guild, member, channel, boosts=1, level_up=None) -> bool:
    await asyncio.sleep(2)   # Discord updates the boost numbers a moment after the message

    text = THANKS_TEXT.format(mention=member.mention, server=guild.name)
    if level_up:
        text = LEVEL_UP_TEXT.format(server=guild.name, level=level_up) + "\n" + text
    allowed = discord.AllowedMentions(users=[member], roles=False, everyone=False)

    try:
        png = await make_card(member, guild, boosts, level_up)
        await channel.send(text, file=discord.File(io.BytesIO(png), filename="boost.png"), allowed_mentions=allowed)
        print(f"💜 [boost] Card posted for {member} (level {guild.premium_tier}, {guild.premium_subscription_count} boosts)")
        return True
    except discord.Forbidden:
        print(f"❌ [boost] I can't send messages / files in #{channel} — check my permissions there")
        return False
    except Exception:
        print("❌ [boost] Card failed, sending a plain thank-you instead:")
        traceback.print_exc()
        try:
            embed = discord.Embed(title="💜 New Server Boost", description=text, color=0xFF5AD2)
            embed.set_thumbnail(url=member.display_avatar.url)
            embed.add_field(name="Level", value=str(guild.premium_tier))
            embed.add_field(name="Boosts", value=str(guild.premium_subscription_count or 0))
            await channel.send(embed=embed, allowed_mentions=allowed)
            return True
        except discord.HTTPException:
            return False


class BoostCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # A listener runs ALONGSIDE any on_message you already have; it never replaces it.
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.guild is None or message.guild.id != GUILD_ID:
            return
        if message.type not in BOOST_TYPES or message.id in _seen:
            return
        _seen.add(message.id)
        if len(_seen) > 500:
            _seen.clear()

        guild, member = message.guild, message.author
        level_up = BOOST_TYPES[message.type]

        boosts = 1
        if message.content and message.content.strip().isdigit():   # only filled if Message Content intent is on
            boosts = max(1, min(int(message.content.strip()), 99))

        channel = (guild.get_channel(BOOST_CHANNEL_ID) if BOOST_CHANNEL_ID else None) or message.channel
        posted = await announce(guild, member, channel, boosts, level_up)

        if posted and DELETE_BOOST_MESSAGE:
            try:
                await message.delete()
            except discord.Forbidden:
                print("ℹ️ [boost] Can't delete Discord's boost message — give the bot Manage Messages there (or DELETE_BOOST_MESSAGE=0)")
            except discord.HTTPException:
                pass


@app_commands.command(name="boosttest", description="Preview the boost card (admins only, only you see it)")
@app_commands.describe(member="Whose avatar and name to use (default: you)", level_up="Preview the LEVEL UNLOCKED card (1-3)")
@app_commands.default_permissions(administrator=True)
@app_commands.checks.has_permissions(administrator=True)
@app_commands.guild_only()
async def boosttest(
    interaction: discord.Interaction,
    member: Optional[discord.Member] = None,
    level_up: Optional[app_commands.Range[int, 1, 3]] = None,
):
    await interaction.response.defer(ephemeral=True)
    target = member or interaction.user
    try:
        png = await make_card(target, interaction.guild, 1, level_up)
    except Exception as e:
        traceback.print_exc()
        return await interaction.followup.send(f"❌ Couldn't draw the card: {e}", ephemeral=True)
    await interaction.followup.send(file=discord.File(io.BytesIO(png), filename="boost_preview.png"), ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(BoostCog(bot))
    # Registered for the ELT server only, next to the commands your bot already has.
    bot.tree.add_command(boosttest, guild=GUILD, override=True)
    print("💜 [boost] Boost cards loaded")


async def teardown(bot: commands.Bot):
    bot.tree.remove_command("boosttest", guild=GUILD)
