"""
Server Wrapped — Discord Stats Bot
───────────────────────────────────
Commands (run in any channel the bot can see):
  !wrapped          → scrape everything and write stats.json
  !wrapped status   → show a quick count without full scrape
  !wrapped preview  → print a summary to the channel

Needs:  DISCORD_TOKEN in .env
Writes: OUTPUT_PATH from config.py  (default: ../web/stats.json)
"""

import os
import re
import json
import asyncio
import logging
import subprocess
import shutil
from datetime import datetime, timezone, timedelta
from collections import defaultdict, Counter

import discord
from discord.ext import commands
from dotenv import load_dotenv
import pytz
import emoji as emoji_lib

from config import CONFIG

# ── Logging ─────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("wrapped")

load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")
if not TOKEN:
    raise RuntimeError("DISCORD_TOKEN not set in .env")

GIT = shutil.which("git") or "git"
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")

# ── Bot setup ────────────────────────────────────────────────────────────────
intents = discord.Intents.default()
intents.message_content = True   # Privileged — must be ON in dev portal
intents.members = True
intents.guilds = True

bot = commands.Bot(command_prefix="!", intents=intents, help_command=None)

# ── Helpers ──────────────────────────────────────────────────────────────────

TZ = pytz.timezone(CONFIG["TIMEZONE"])

def to_local(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(TZ)

def parse_date(s: str | None) -> datetime | None:
    if not s:
        return None
    return TZ.localize(datetime.strptime(s, "%Y-%m-%d"))

DATE_FROM = parse_date(CONFIG["DATE_FROM"])
DATE_TO   = parse_date(CONFIG["DATE_TO"]) if CONFIG["DATE_TO"] else None


UNICODE_EMOJI_RE = re.compile(
    "[\U00010000-\U0010ffff"
    "\U0001F300-\U0001F9FF"
    "\u2600-\u27BF"
    "\u2300-\u23FF"
    "]+",
    flags=re.UNICODE,
)
CUSTOM_EMOJI_RE = re.compile(r"<a?:[a-zA-Z0-9_]+:\d+>")
QUESTION_RE     = re.compile(r"\?")


def extract_emojis(text: str) -> list[str]:
    found = []
    # Unicode emojis
    for match in UNICODE_EMOJI_RE.finditer(text):
        for char in match.group():
            if emoji_lib.is_emoji(char):
                found.append(char)
    # Custom Discord emojis  (:name:)
    for match in CUSTOM_EMOJI_RE.finditer(text):
        found.append(match.group().split(":")[1])  # just the name
    return found


def matches_bucket(text: str, keywords: list[str]) -> bool:
    lower = text.lower()
    return any(kw in lower for kw in keywords)


def safe_message_preview(msg: discord.Message, max_len: int = 200) -> dict:
    return {
        "author":    str(msg.author.display_name),
        "content":   msg.content[:max_len],
        "timestamp": msg.created_at.isoformat(),
        "channel":   msg.channel.name if hasattr(msg.channel, "name") else "DM",
        "jump_url":  msg.jump_url,
    }


# ── Core scraper ─────────────────────────────────────────────────────────────

async def scrape_guild(guild: discord.Guild, status_msg: discord.Message | None = None):
    log.info(f"Starting scrape for guild: {guild.name}")

    total_messages      = 0
    sender_counts       = Counter()     # display_name → count
    emoji_counts        = Counter()
    channel_counts      = Counter()
    hourly_counts       = defaultdict(int)    # 0-23 → count
    monthly_counts      = defaultdict(int)    # "YYYY-MM" → count
    midnight_questions  = 0
    bucket_counts       = {k: 0 for k in CONFIG["KEYWORD_BUCKETS"]}
    bucket_samples      = {k: [] for k in CONFIG["KEYWORD_BUCKETS"]}
    mention_counts      = defaultdict(int)    # member_id → count (who got mentioned)

    channels_to_scrape = _get_channels(guild)
    log.info(f"Channels to scrape: {[c.name for c in channels_to_scrape]}")

    for idx, channel in enumerate(channels_to_scrape):
        log.info(f"  [{idx+1}/{len(channels_to_scrape)}] #{channel.name}")

        if status_msg:
            try:
                await status_msg.edit(
                    content=f"⏳ Scraping `#{channel.name}` ({idx+1}/{len(channels_to_scrape)})…"
                )
            except Exception:
                pass

        try:
            async for msg in channel.history(
                limit=None,
                after=DATE_FROM,
                before=DATE_TO,
                oldest_first=True,
            ):
                if msg.author.bot:
                    continue

                total_messages += 1
                local_dt = to_local(msg.created_at)

                # ── Sender ──────────────────────────────────────────────────
                sender_counts[msg.author.display_name] += 1

                # ── Channel ─────────────────────────────────────────────────
                channel_counts[channel.name] += 1

                # ── Time buckets ────────────────────────────────────────────
                hour = local_dt.hour
                hourly_counts[hour] += 1
                monthly_counts[local_dt.strftime("%Y-%m")] += 1

                # ── Emojis ──────────────────────────────────────────────────
                for e in extract_emojis(msg.content):
                    emoji_counts[e] += 1
                # Also count reaction emojis
                for rxn in msg.reactions:
                    key = str(rxn.emoji) if isinstance(rxn.emoji, str) else rxn.emoji.name
                    emoji_counts[key] += rxn.count

                # ── Mentions ────────────────────────────────────────────────
                for member in msg.mentions:
                    mention_counts[member.display_name] += 1

                # ── Midnight zone questions ─────────────────────────────────
                mz_start = CONFIG["MIDNIGHT_ZONE_START"]
                mz_end   = CONFIG["MIDNIGHT_ZONE_END"]
                in_midnight = (
                    (mz_start < mz_end and mz_start <= hour < mz_end) or
                    (mz_start > mz_end and (hour >= mz_start or hour < mz_end))
                )
                if in_midnight and QUESTION_RE.search(msg.content):
                    midnight_questions += 1

                # ── Keyword buckets ─────────────────────────────────────────
                for bucket, keywords in CONFIG["KEYWORD_BUCKETS"].items():
                    if matches_bucket(msg.content, keywords):
                        bucket_counts[bucket] += 1
                        if len(bucket_samples[bucket]) < CONFIG["SAMPLE_MESSAGES"]:
                            bucket_samples[bucket].append(safe_message_preview(msg))

        except discord.Forbidden:
            log.warning(f"  No permission to read #{channel.name}, skipping")
        except Exception as e:
            log.error(f"  Error reading #{channel.name}: {e}")

        await asyncio.sleep(0.3)   # polite rate-limiting

    log.info(f"Scrape complete. {total_messages:,} messages processed.")

    # ── Build output ─────────────────────────────────────────────────────────
    top_n     = CONFIG["TOP_SENDERS_COUNT"]
    top_emoji = CONFIG["TOP_EMOJIS_COUNT"]
    top_chan  = CONFIG["TOP_CHANNELS_COUNT"]

    stats = {
        "generated_at":  datetime.now(TZ).isoformat(),
        "server_name":   guild.name,
        "server_icon":   str(guild.icon.url) if guild.icon else None,
        "date_range": {
            "from": CONFIG["DATE_FROM"] or "beginning",
            "to":   CONFIG["DATE_TO"]   or datetime.now(TZ).strftime("%Y-%m-%d"),
        },
        "total_messages":     total_messages,
        "midnight_questions": midnight_questions,

        "top_senders": [
            {"name": name, "count": count}
            for name, count in sender_counts.most_common(top_n)
        ],

        "top_emojis": [
            {"emoji": e, "count": c}
            for e, c in emoji_counts.most_common(top_emoji)
        ],

        "top_channels": [
            {"name": name, "count": count}
            for name, count in channel_counts.most_common(top_chan)
        ],

        "top_mentioned": [
            {"name": name, "count": count}
            for name, count in sorted(
                mention_counts.items(), key=lambda x: x[1], reverse=True
            )[:top_n]
        ],

        "keyword_buckets": {
            bucket: {
                "count":   bucket_counts[bucket],
                "samples": bucket_samples[bucket],
            }
            for bucket in CONFIG["KEYWORD_BUCKETS"]
        },

        "hourly_activity": dict(sorted(hourly_counts.items())),
        "monthly_activity": dict(sorted(monthly_counts.items())),

        "midnight_zone": {
            "start": CONFIG["MIDNIGHT_ZONE_START"],
            "end":   CONFIG["MIDNIGHT_ZONE_END"],
        },
    }

    return stats


def _get_channels(guild: discord.Guild) -> list[discord.TextChannel]:
    configured_ids = [int(x) for x in CONFIG["CHANNEL_IDS"] if x]
    exclude_names  = [x.lower() for x in CONFIG["EXCLUDE_CHANNELS"]]

    channels = []
    for ch in guild.text_channels:
        if configured_ids and ch.id not in configured_ids:
            continue
        if any(ex in ch.name.lower() for ex in exclude_names):
            continue
        if not ch.permissions_for(guild.me).read_message_history:
            continue
        channels.append(ch)

    return channels


# ── Commands ──────────────────────────────────────────────────────────────────

@bot.event
async def on_ready():
    log.info(f"Bot ready as {bot.user} (ID: {bot.user.id})")
    log.info(f"Connected to {len(bot.guilds)} guild(s)")
    await bot.change_presence(activity=discord.Activity(
        type=discord.ActivityType.watching,
        name="your memories 👀"
    ))


@bot.command(name="wrapped")
@commands.has_permissions(manage_messages=True)
async def wrapped_cmd(ctx: commands.Context, subcommand: str = ""):
    """
    !wrapped          → full scrape + write stats.json
    !wrapped status   → quick message count per channel
    !wrapped preview  → scrape + post a summary embed (no file write)
    """

    if subcommand == "status":
        await _cmd_status(ctx)
        return

    if subcommand == "clear":
        blank = {"_note": "Cleared. Run !wrapped to regenerate."}
        out_path = os.path.join(os.path.dirname(__file__), CONFIG["OUTPUT_PATH"])
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(blank, f, indent=2)
        await ctx.send("🗑️ `stats.json` cleared.")
        return

    # ── Full scrape ──────────────────────────────────────────────────────────
    status_msg = await ctx.send("⏳ Starting scrape… this may take a few minutes.")

    try:
        stats = await scrape_guild(ctx.guild, status_msg)
    except Exception as e:
        await status_msg.edit(content=f"❌ Scrape failed: `{e}`")
        log.exception("Scrape error")
        return

    # Write JSON
    out_path = os.path.join(os.path.dirname(__file__), CONFIG["OUTPUT_PATH"])
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(stats, f, ensure_ascii=False, indent=2)

    log.info(f"Stats written to {out_path}")

    # Reply with a quick summary embed
    embed = _build_summary_embed(stats)
    await status_msg.edit(content="✅ Done! Stats written to `stats.json`.", embed=embed)

    if subcommand == "preview":
        return

    # Auto-commit and push updated stats when there are staged changes.
    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    rel_out_path = os.path.relpath(os.path.abspath(out_path), repo_root)

    push_target = "origin"
    if GITHUB_TOKEN:
        try:
            origin_url = subprocess.run(
                [GIT, "remote", "get-url", "origin"],
                cwd=repo_root,
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
            if origin_url.startswith("https://github.com/"):
                push_target = origin_url.replace(
                    "https://github.com/",
                    f"https://x-access-token:{GITHUB_TOKEN}@github.com/",
                    1,
                )
        except subprocess.CalledProcessError:
            pass

    try:
        subprocess.run(
            [GIT, "add", rel_out_path],
            cwd=repo_root,
            check=True,
            capture_output=True,
            text=True,
        )

        has_staged_changes = subprocess.run(
            [GIT, "diff", "--cached", "--quiet"],
            cwd=repo_root,
            check=False,
        ).returncode != 0

        if has_staged_changes:
            subprocess.run(
                [
                    GIT,
                    "-c", "user.email=bot@wrapped.local",
                    "-c", "user.name=Server Wrapped Bot",
                    "commit", "-m", "chore: update wrapped stats",
                ],
                cwd=repo_root,
                check=True,
                capture_output=True,
                text=True,
            )
            subprocess.run(
                [GIT, "push", push_target, "HEAD:main"],
                cwd=repo_root,
                check=True,
                capture_output=True,
                text=True,
            )
            await ctx.send("✅ Stats committed and pushed successfully.")
        else:
            await ctx.send("ℹ️ No changes detected in stats file; nothing to commit.")

    except FileNotFoundError as e:
        await ctx.send("⚠️ Git automation failed: `git` was not found in this environment.")
        log.error(f"Git automation failed: {e}")
    except subprocess.CalledProcessError as e:
        err = (e.stderr or e.stdout or str(e)).strip()
        await ctx.send(f"⚠️ Git automation failed: `{err}`")
        log.error(f"Git automation failed: {err}")


async def _cmd_status(ctx: commands.Context):
    channels = _get_channels(ctx.guild)
    lines = [f"📡 **{len(channels)} channels** will be scraped:\n"]
    for ch in channels[:20]:
        lines.append(f"  • #{ch.name}")
    if len(channels) > 20:
        lines.append(f"  … and {len(channels)-20} more")
    await ctx.send("\n".join(lines))


def _build_summary_embed(stats: dict) -> discord.Embed:
    embed = discord.Embed(
        title=f"🎉 {stats['server_name']} — Server Wrapped",
        color=0x5865F2,
        timestamp=datetime.fromisoformat(stats["generated_at"]),
    )
    embed.add_field(name="📨 Total Messages",     value=f"{stats['total_messages']:,}",     inline=True)
    embed.add_field(name="🌙 Midnight Questions", value=f"{stats['midnight_questions']:,}", inline=True)

    top3 = ", ".join(
        f"**{s['name']}** ({s['count']:,})"
        for s in stats["top_senders"][:3]
    )
    embed.add_field(name="🏆 Top Senders",  value=top3 or "—",  inline=False)

    top3e = "  ".join(s["emoji"] for s in stats["top_emojis"][:5])
    embed.add_field(name="🔥 Top Emojis",  value=top3e or "—", inline=False)

    for bucket, data in stats["keyword_buckets"].items():
        label = bucket.replace("_", " ").title()
        embed.add_field(name=label, value=f"{data['count']:,} messages", inline=True)

    embed.set_footer(text=f"Range: {stats['date_range']['from']} → {stats['date_range']['to']}")
    return embed


@wrapped_cmd.error
async def wrapped_error(ctx, error):
    if isinstance(error, commands.MissingPermissions):
        await ctx.send("❌ You need **Manage Messages** permission to run `!wrapped`.")
    else:
        await ctx.send(f"❌ Error: `{error}`")
        log.error(f"Command error: {error}")


# ── Run ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    bot.run(TOKEN)
