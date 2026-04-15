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
import base64
from contextlib import suppress
from datetime import datetime, timezone, timedelta
from collections import defaultdict, Counter

import aiohttp
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

GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
GITHUB_REPO = os.getenv("GITHUB_REPO")

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
    try:
        return TZ.localize(datetime.strptime(s, "%Y-%m-%d"))
    except ValueError as exc:
        raise RuntimeError(f"Invalid date in config ({s}). Use YYYY-MM-DD.") from exc

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
SCRAPE_LOCK     = asyncio.Lock()


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


def in_midnight_zone(hour: int, start: int, end: int) -> bool:
    if start == end:
        return True
    if start < end:
        return start <= hour < end
    return hour >= start or hour < end


def build_spotlight_mentions(mention_counts: dict[str, int]) -> list[dict]:
    spotlight_names = [n.strip().lower() for n in CONFIG.get("SPOTLIGHT_NAMES", []) if n.strip()]
    if not spotlight_names:
        return []

    spotlight = []
    for name, count in mention_counts.items():
        lower_name = name.lower()
        if any(target in lower_name for target in spotlight_names):
            spotlight.append({"name": name, "count": count})

    spotlight.sort(key=lambda x: x["count"], reverse=True)
    return spotlight


async def push_stats_via_api(stats_json: str) -> str:
    token = GITHUB_TOKEN
    repo = GITHUB_REPO

    if not token or not repo:
        return "⚠️ GITHUB_TOKEN or GITHUB_REPO not set in env variables."

    file_path = "web/stats.json"
    api_url = f"https://api.github.com/repos/{repo}/contents/{file_path}"
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }

    timeout = aiohttp.ClientTimeout(total=30)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        sha = None
        try:
            async with session.get(api_url, headers=headers) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    sha = data.get("sha")
                elif resp.status != 404:
                    err = await resp.text()
                    return f"⚠️ GitHub API error {resp.status}: {err[:200]}"
        except aiohttp.ClientError as exc:
            return f"⚠️ Could not contact GitHub API: {exc}"

        encoded = base64.b64encode(stats_json.encode("utf-8")).decode("ascii")
        payload = {
            "message": "chore: update wrapped stats",
            "content": encoded,
            "committer": {
                "name": "Server Wrapped Bot",
                "email": "bot@wrapped.local",
            },
        }
        if sha:
            payload["sha"] = sha

        try:
            async with session.put(api_url, headers=headers, json=payload) as resp:
                if resp.status in (200, 201):
                    return "✅ Stats pushed to GitHub — Vercel redeploying now!"
                err = await resp.text()
                return f"⚠️ GitHub API error {resp.status}: {err[:200]}"
        except aiohttp.ClientError as exc:
            return f"⚠️ Failed to push stats to GitHub: {exc}"


# ── Core scraper ─────────────────────────────────────────────────────────────

async def scrape_guild(guild: discord.Guild, status_msg: discord.Message | None = None):
    log.info(f"Starting scrape for guild: {guild.name}")
    started_at = datetime.now(timezone.utc)

    total_messages      = 0
    sender_counts       = Counter()     # display_name → count
    active_member_ids   = set()
    emoji_counts        = Counter()
    channel_counts      = Counter()
    hourly_counts       = defaultdict(int)    # 0-23 → count
    weekday_counts      = defaultdict(int)    # Monday-Sunday
    monthly_counts      = defaultdict(int)    # "YYYY-MM" → count
    midnight_questions  = 0
    bucket_counts       = {k: 0 for k in CONFIG["KEYWORD_BUCKETS"]}
    bucket_samples      = {k: [] for k in CONFIG["KEYWORD_BUCKETS"]}
    mention_counts      = defaultdict(int)    # member_id → count (who got mentioned)

    channels_to_scrape, skipped_channels = _classify_channels(guild)
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
                active_member_ids.add(msg.author.id)

                # ── Channel ─────────────────────────────────────────────────
                channel_counts[channel.name] += 1

                # ── Time buckets ────────────────────────────────────────────
                hour = local_dt.hour
                hourly_counts[hour] += 1
                weekday_counts[local_dt.strftime("%A")] += 1
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
                in_midnight = in_midnight_zone(hour, mz_start, mz_end)
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
    duration_seconds = round((datetime.now(timezone.utc) - started_at).total_seconds(), 2)

    stats = {
        "generated_at":  datetime.now(TZ).isoformat(),
        "server_name":   guild.name,
        "server_icon":   str(guild.icon.url) if guild.icon else None,
        "date_range": {
            "from": CONFIG["DATE_FROM"] or "beginning",
            "to":   CONFIG["DATE_TO"]   or datetime.now(TZ).strftime("%Y-%m-%d"),
        },
        "total_messages":     total_messages,
        "active_members":     len(active_member_ids),
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

        "spotlight_mentions": build_spotlight_mentions(mention_counts),

        "keyword_buckets": {
            bucket: {
                "count":   bucket_counts[bucket],
                "samples": bucket_samples[bucket],
            }
            for bucket in CONFIG["KEYWORD_BUCKETS"]
        },

        "hourly_activity": dict(sorted(hourly_counts.items())),
        "weekday_activity": {
            day: weekday_counts.get(day, 0)
            for day in ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
        },
        "monthly_activity": dict(sorted(monthly_counts.items())),

        "midnight_zone": {
            "start": CONFIG["MIDNIGHT_ZONE_START"],
            "end":   CONFIG["MIDNIGHT_ZONE_END"],
        },

        "scrape_meta": {
            "channels_scraped": len(channels_to_scrape),
            "channels_skipped": skipped_channels,
            "duration_seconds": duration_seconds,
        },
    }

    return stats


def _classify_channels(guild: discord.Guild) -> tuple[list[discord.TextChannel], dict[str, int]]:
    configured_ids = [int(x) for x in CONFIG["CHANNEL_IDS"] if x]
    exclude_names  = [x.lower() for x in CONFIG["EXCLUDE_CHANNELS"]]
    channels = []
    skipped = defaultdict(int)

    bot_member = guild.me or guild.get_member(bot.user.id)
    if bot_member is None:
        skipped["bot_not_visible"] = len(guild.text_channels)
        return channels, dict(skipped)

    for ch in guild.text_channels:
        if configured_ids and ch.id not in configured_ids:
            skipped["not_in_channel_ids"] += 1
            continue
        if any(ex in ch.name.lower() for ex in exclude_names):
            skipped["excluded_by_name"] += 1
            continue
        perms = ch.permissions_for(bot_member)
        if not (perms.view_channel and perms.read_message_history):
            skipped["missing_permissions"] += 1
            continue
        channels.append(ch)

    return channels, dict(skipped)


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

    subcommand = (subcommand or "").strip().lower()

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
    if SCRAPE_LOCK.locked():
        await ctx.send("⏳ A wrapped scrape is already running. Please wait for it to finish.")
        return

    status_msg = await ctx.send("⏳ Starting scrape… this may take a few minutes.")

    async with SCRAPE_LOCK:
        try:
            stats = await scrape_guild(ctx.guild, status_msg)
        except Exception as e:
            with suppress(Exception):
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

    stats_json = json.dumps(stats, ensure_ascii=False, indent=2)
    msg = await push_stats_via_api(stats_json)
    await ctx.send(msg)


async def _cmd_status(ctx: commands.Context):
    channels, skipped = _classify_channels(ctx.guild)
    lines = [f"📡 **{len(channels)} channels** will be scraped:\n"]
    for ch in channels[:20]:
        lines.append(f"  • #{ch.name}")
    if len(channels) > 20:
        lines.append(f"  … and {len(channels)-20} more")

    if skipped:
        lines.append("\n⏭️ Skipped channels:")
        for reason, count in sorted(skipped.items()):
            lines.append(f"  • {reason}: {count}")

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
