"""
Server Wrapped — Discord Stats Bot
───────────────────────────────────
Commands (run in any channel the bot can see):
  !wrapped          → scrape everything and write stats.json
  !wrapped status   → show a quick count without full scrape
  !wrapped preview  → print a summary to the channel
    !wrapped vote     → cast or inspect category votes

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
VOTES_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "web", "votes.json"))

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
TOKEN_RE        = re.compile(r"[a-z0-9'-]+", re.IGNORECASE)
SCRAPE_LOCK     = asyncio.Lock()


def _slugify(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")


def _build_vote_categories() -> dict[str, dict]:
    raw = CONFIG.get("VOTE_CATEGORIES", {})
    categories: dict[str, dict] = {}

    if not isinstance(raw, dict):
        return categories

    for key, data in raw.items():
        slug = _slugify(str(key))
        if not slug:
            continue

        if isinstance(data, str):
            meta = {"label": data.strip() or slug.replace("_", " ").title(), "emoji": "🗳️", "description": ""}
        elif isinstance(data, dict):
            meta = {
                "label": str(data.get("label") or slug.replace("_", " ").title()),
                "emoji": str(data.get("emoji") or "🗳️"),
                "description": str(data.get("description") or ""),
            }
        else:
            continue

        categories[slug] = meta

    return categories


VOTE_CATEGORIES = _build_vote_categories()

SWEAR_WORDS = {
    "fuck", "shit", "bitch", "asshole", "dick", "bastard", "slut",
    "retard", "cunt", "fucker", "cock",
}

# Common ass-ending swear forms, including hyphenated variants.
ASS_SWEAR_FORMS = {
    "ass",
    "badass", "bad-ass",
    "smartass", "smart-ass",
    "dumbass", "dumb-ass",
    "jackass", "jack-ass",
    "kickass", "kick-ass",
    "hardass", "hard-ass",
    "deadass", "dead-ass",
    "realass", "real-ass",
    "crazyass", "crazy-ass",
    "oldass", "old-ass",
    "lazyass", "lazy-ass",
    "bigass", "big-ass",
    "fatass", "fat-ass",
    "uglyass", "ugly-ass",
    "stupidass", "stupid-ass",
    "shitass", "shit-ass",
    "asshat", "asswipe", "assface", "assbag", "assclown", "asslick",
}

ASS_SWEAR_PREFIXES = {
    "bad", "smart", "dumb", "jack", "kick", "hard", "dead", "real",
    "crazy", "old", "lazy", "big", "fat", "ugly", "stupid", "shit",
    "mad", "wild",
}


def _build_keyword_matchers() -> dict[str, list[dict]]:
    """Precompile keyword matchers for fast per-message checks."""
    substring_ok = {
        kw.strip().lower()
        for kw in CONFIG.get("KEYWORD_SUBSTRING_MATCH", ["shit"])
        if isinstance(kw, str) and kw.strip()
    }

    matchers: dict[str, list[dict]] = {}
    for bucket, keywords in CONFIG["KEYWORD_BUCKETS"].items():
        bucket_matchers: list[dict] = []
        for kw in keywords:
            if not isinstance(kw, str):
                continue
            norm_kw = kw.strip().lower()
            if not norm_kw:
                continue

            if norm_kw in substring_ok:
                bucket_matchers.append({"type": "substring", "value": norm_kw})
                continue

            escaped = re.escape(norm_kw).replace(r"\ ", r"\s+")
            # Default behavior: match only as a whole token/phrase (word boundaries).
            pattern = re.compile(rf"(?<![a-z0-9']){escaped}(?![a-z0-9'])", re.IGNORECASE)
            bucket_matchers.append({"type": "regex", "value": pattern})

        matchers[bucket] = bucket_matchers

    return matchers


KEYWORD_MATCHERS = _build_keyword_matchers()


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


def contains_swear(text: str) -> bool:
    """Return True if text contains a tracked swear term."""
    lowered = text.lower().replace("’", "'")

    for token in TOKEN_RE.findall(lowered):
        clean = token.strip("'\"")
        if not clean:
            continue

        compact = clean.replace("-", "")
        if compact in SWEAR_WORDS:
            return True

        if compact in ASS_SWEAR_FORMS:
            return True

        if compact.endswith("ass") and len(compact) > 3:
            prefix = compact[:-3]
            if prefix in ASS_SWEAR_PREFIXES:
                return True

    return False


def matches_bucket(text: str, bucket: str) -> bool:
    """Check if text matches any keyword pattern in a bucket."""
    if bucket == "swear_words":
        return contains_swear(text)

    lower = text.lower()
    for matcher in KEYWORD_MATCHERS.get(bucket, []):
        if matcher["type"] == "substring":
            if matcher["value"] in lower:
                return True
            continue
        if matcher["type"] == "regex" and matcher["value"].search(lower):
            return True
    return False


def recency_weight(message_dt: datetime, start_dt: datetime, end_dt: datetime) -> float:
    """Return a weight in [1.0, 2.0] so newer messages count more."""
    total_window = (end_dt - start_dt).total_seconds()
    if total_window <= 0:
        return 1.0
    elapsed = (message_dt - start_dt).total_seconds()
    ratio = max(0.0, min(1.0, elapsed / total_window))
    return 1.0 + ratio


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


def _vote_categories_for_menu() -> list[discord.SelectOption]:
    options: list[discord.SelectOption] = []
    for key, meta in list(VOTE_CATEGORIES.items())[:25]:
        options.append(
            discord.SelectOption(
                label=(meta.get("label") or key.replace("_", " ").title())[:100],
                value=key,
                emoji=meta.get("emoji") or "🗳️",
                description=(meta.get("description") or "")[:100] or None,
            )
        )
    return options


class VotePanelView(discord.ui.View):
    def __init__(self, guild: discord.Guild, owner_id: int):
        super().__init__(timeout=900)
        self.guild = guild
        self.owner_id = owner_id
        self.selected_category: str | None = None
        self.selected_target: discord.abc.User | None = None

        self.category_select = VoteCategorySelect()
        self.person_select = VotePersonSelect()
        self.submit_button = VoteSubmitButton()

        self.add_item(self.category_select)
        self.add_item(self.person_select)
        self.add_item(self.submit_button)

    def summary_text(self) -> str:
        return (
            "🗳️ **Voting panel**\n"
            "Pick a category and a person, then press **Submit vote**.\n"
            "Your selections and confirmation are private."
        )

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("This voting panel belongs to someone else.", ephemeral=True)
            return False
        return True

    async def submit_vote(self, interaction: discord.Interaction) -> None:
        if not self.selected_category:
            await interaction.response.send_message("Choose a category first.", ephemeral=True)
            return

        if self.selected_target is None:
            await interaction.response.send_message("Choose a person first.", ephemeral=True)
            return

        target_member = self.guild.get_member(self.selected_target.id)
        if target_member is None:
            await _respond_private_interaction(interaction, "That person is not in this server.")
            return

        confirmation = await _save_vote(self.guild, interaction.user, self.selected_category, target_member)
        await _respond_private_interaction(interaction, confirmation)


class VoteCategorySelect(discord.ui.Select):
    def __init__(self):
        options = _vote_categories_for_menu()
        placeholder = "Choose a category"
        if not options:
            options = [discord.SelectOption(label="No categories configured", value="none")]
            placeholder = "No categories configured"

        super().__init__(
            placeholder=placeholder,
            min_values=1,
            max_values=1,
            options=options,
            row=0,
        )

    async def callback(self, interaction: discord.Interaction):
        view = self.view
        if not isinstance(view, VotePanelView):
            return

        if self.values[0] == "none":
            await _respond_private_interaction(interaction, "No categories are configured.")
            return

        view.selected_category = self.values[0]
        label = VOTE_CATEGORIES.get(view.selected_category, {}).get("label") or "category"
        await _respond_private_interaction(interaction, f"Selected category: **{label}**")


class VotePersonSelect(discord.ui.UserSelect):
    def __init__(self):
        super().__init__(placeholder="Choose a person", min_values=1, max_values=1, row=1)

    async def callback(self, interaction: discord.Interaction):
        view = self.view
        if not isinstance(view, VotePanelView):
            return

        view.selected_target = self.values[0]
        selected_name = getattr(view.selected_target, "display_name", None) or getattr(view.selected_target, "name", "Unknown")
        await _respond_private_interaction(interaction, f"Selected person: **{selected_name}**")


class VoteSubmitButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label="Submit vote", style=discord.ButtonStyle.primary, emoji="✅", row=2)

    async def callback(self, interaction: discord.Interaction):
        view = self.view
        if not isinstance(view, VotePanelView):
            return
        await view.submit_vote(interaction)


def _empty_vote_store() -> dict:
    return {"guilds": {}}


def load_vote_store() -> dict:
    if not os.path.exists(VOTES_PATH):
        return _empty_vote_store()

    try:
        with open(VOTES_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            data.setdefault("guilds", {})
            return data
    except Exception as exc:
        log.warning(f"Could not read votes store: {exc}")

    return _empty_vote_store()


def save_vote_store(store: dict) -> None:
    os.makedirs(os.path.dirname(VOTES_PATH), exist_ok=True)
    with open(VOTES_PATH, "w", encoding="utf-8") as f:
        json.dump(store, f, ensure_ascii=False, indent=2)


def _get_guild_vote_state(store: dict, guild_id: int) -> dict:
    guilds = store.setdefault("guilds", {})
    guild_state = guilds.setdefault(str(guild_id), {})
    guild_state.setdefault("ballots", {})
    return guild_state


def _resolve_vote_category(raw: str | None) -> str | None:
    if not raw:
        return None

    key = _slugify(raw)
    if key in VOTE_CATEGORIES:
        return key

    for category_key, meta in VOTE_CATEGORIES.items():
        if _slugify(meta.get("label", "")) == key:
            return category_key

    return None


def _member_vote_payload(member: discord.Member) -> dict:
    return {
        "target_id": str(member.id),
        "target_name": member.display_name,
        "target_avatar": str(member.display_avatar.url),
        "voted_at": datetime.now(timezone.utc).isoformat(),
    }


def build_vote_results(guild: discord.Guild, store: dict) -> list[dict]:
    guild_state = store.get("guilds", {}).get(str(guild.id), {})
    ballots_by_category = guild_state.get("ballots", {})

    results: list[dict] = []
    for category_key, meta in VOTE_CATEGORIES.items():
        ballots = ballots_by_category.get(category_key, {}) or {}
        tallies: Counter[str] = Counter()
        target_meta: dict[str, dict] = {}

        for ballot in ballots.values():
            target_id = str(ballot.get("target_id") or "")
            if not target_id:
                continue
            tallies[target_id] += 1
            target_meta[target_id] = ballot

        winners: list[dict] = []
        if tallies:
            max_votes = max(tallies.values())
            winner_ids = [target_id for target_id, count in tallies.items() if count == max_votes]
            winner_ids.sort(key=lambda target_id: target_meta.get(target_id, {}).get("target_name", "").lower())

            for target_id in winner_ids:
                ballot = target_meta.get(target_id, {})
                member = guild.get_member(int(target_id)) if target_id.isdigit() else None
                winners.append({
                    "id": target_id,
                    "name": (member.display_name if member else ballot.get("target_name") or "Unknown"),
                    "avatar_url": (str(member.display_avatar.url) if member else ballot.get("target_avatar")),
                    "votes": tallies[target_id],
                })

        results.append({
            "key": category_key,
            "label": meta.get("label") or category_key.replace("_", " ").title(),
            "emoji": meta.get("emoji") or "🗳️",
            "description": meta.get("description") or "",
            "total_ballots": len(ballots),
            "vote_count": (max(tallies.values()) if tallies else 0),
            "winners": winners,
        })

    return results


def apply_vote_results_to_stats(stats: dict, guild: discord.Guild) -> dict:
    store = load_vote_store()
    stats["vote_categories"] = [
        {"key": key, **meta}
        for key, meta in VOTE_CATEGORIES.items()
    ]
    stats["as_voted_by_you"] = build_vote_results(guild, store)
    return stats


def _write_current_vote_results_to_stats(guild: discord.Guild) -> str | None:
    out_path = os.path.join(os.path.dirname(__file__), CONFIG["OUTPUT_PATH"])
    if not os.path.exists(out_path):
        return None

    try:
        with open(out_path, "r", encoding="utf-8") as f:
            stats = json.load(f)
        if not isinstance(stats, dict):
            return None
    except Exception as exc:
        log.warning(f"Could not update stats.json with vote results: {exc}")
        return None

    apply_vote_results_to_stats(stats, guild)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(stats, f, ensure_ascii=False, indent=2)

    return json.dumps(stats, ensure_ascii=False, indent=2)


async def _save_vote(
    guild: discord.Guild,
    voter: discord.abc.User,
    category_key: str,
    target_member: discord.Member,
) -> str:
    store = load_vote_store()
    guild_state = _get_guild_vote_state(store, guild.id)
    ballots = guild_state["ballots"].setdefault(category_key, {})
    ballots[str(voter.id)] = _member_vote_payload(target_member)
    guild_state["updated_at"] = datetime.now(timezone.utc).isoformat()
    save_vote_store(store)

    await push_file_via_api(
        "web/votes.json",
        json.dumps(store, ensure_ascii=False, indent=2),
        "chore: update wrapped votes",
        "✅ Vote tally saved to GitHub.",
    )

    stats_json = _write_current_vote_results_to_stats(guild)
    if stats_json:
        await push_stats_via_api(stats_json)

    results = build_vote_results(guild, store)
    current = next((item for item in results if item["key"] == category_key), None)
    label = VOTE_CATEGORIES[category_key]["label"]
    winner_text = ""
    if current and current["winners"]:
        winner = current["winners"][0]
        winner_text = f" Current leader: **{winner['name']}** with {winner['votes']} votes."

    return f"✅ Vote saved for **{label}**.{winner_text}"


async def _send_private_vote_ack(ctx: commands.Context, message: str) -> None:
    try:
        await ctx.author.send(message)
    except discord.Forbidden:
        await ctx.send(
            "✅ Vote saved. I couldn't DM you, so this confirmation will disappear shortly.",
            delete_after=8,
        )


async def _send_watching_dm(ctx: commands.Context) -> None:
    with suppress(discord.Forbidden, discord.HTTPException):
        await ctx.author.send("im watching 👀")


async def _respond_private_interaction(interaction: discord.Interaction, message: str) -> None:
    use_ephemeral = interaction.guild is not None
    if interaction.response.is_done():
        await interaction.followup.send(message, ephemeral=use_ephemeral)
    else:
        await interaction.response.send_message(message, ephemeral=use_ephemeral)


async def _send_vote_panel_in_server(ctx: commands.Context, preselected_category: str | None = None) -> bool:
    view = VotePanelView(ctx.guild, owner_id=ctx.author.id)
    if preselected_category:
        view.selected_category = preselected_category

    await ctx.send(view.summary_text(), view=view)

    with suppress(discord.Forbidden, discord.HTTPException):
        await ctx.message.delete()
    return True


async def push_file_via_api(file_path: str, file_content: str, commit_message: str, success_message: str) -> str:
    token = GITHUB_TOKEN
    repo = GITHUB_REPO

    if not token or not repo:
        return "⚠️ GITHUB_TOKEN or GITHUB_REPO not set in env variables."

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

        encoded = base64.b64encode(file_content.encode("utf-8")).decode("ascii")
        payload = {
            "message": commit_message,
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
                    return success_message
                err = await resp.text()
                return f"⚠️ GitHub API error {resp.status}: {err[:200]}"
        except aiohttp.ClientError as exc:
            return f"⚠️ Failed to push stats to GitHub: {exc}"


async def push_stats_via_api(stats_json: str) -> str:
    return await push_file_via_api(
        "web/stats.json",
        stats_json,
        "chore: update wrapped stats",
        "✅ Stats pushed to GitHub — Vercel redeploying now!",
    )


# ── Core scraper ─────────────────────────────────────────────────────────────

async def scrape_guild(guild: discord.Guild, status_msg: discord.Message | None = None):
    log.info(f"Starting scrape for guild: {guild.name}")
    started_at = datetime.now(timezone.utc)

    total_messages      = 0
    sender_counts       = Counter()     # display_name → count
    sender_message_counts = Counter()   # member_id → count
    sender_swear_counts = Counter()     # member_id → swear-message count
    sender_meta         = {}            # member_id → {name, avatar_url}
    active_member_ids   = set()
    emoji_counts        = Counter()
    channel_counts      = Counter()
    hourly_counts       = defaultdict(int)    # 0-23 → count
    weekday_counts      = defaultdict(int)    # Monday-Sunday
    monthly_counts      = defaultdict(int)    # "YYYY-MM" → count
    midnight_questions  = 0
    bucket_counts       = {k: 0 for k in CONFIG["KEYWORD_BUCKETS"]}
    bucket_weighted     = {k: 0.0 for k in CONFIG["KEYWORD_BUCKETS"]}
    bucket_samples      = {k: [] for k in CONFIG["KEYWORD_BUCKETS"]}
    mention_counts      = defaultdict(int)    # member_id → count (who got mentioned)

    channels_to_scrape, skipped_channels = _classify_channels(guild)
    log.info(f"Channels to scrape: {[c.name for c in channels_to_scrape]}")

    range_start_dt = DATE_FROM or TZ.localize(datetime(2000, 1, 1))
    range_end_dt = DATE_TO or datetime.now(TZ)

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
                oldest_first=False,
            ):
                if msg.author.bot:
                    continue

                total_messages += 1
                local_dt = to_local(msg.created_at)

                # ── Sender ──────────────────────────────────────────────────
                sender_counts[msg.author.display_name] += 1
                sender_message_counts[msg.author.id] += 1
                sender_meta[msg.author.id] = {
                    "name": msg.author.display_name,
                    "avatar_url": str(msg.author.display_avatar.url),
                }
                active_member_ids.add(msg.author.id)

                if contains_swear(msg.content):
                    sender_swear_counts[msg.author.id] += 1

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
                    if matches_bucket(msg.content, bucket):
                        bucket_counts[bucket] += 1
                        bucket_weighted[bucket] += recency_weight(local_dt, range_start_dt, range_end_dt)
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

    top_swearers = []
    for member_id, swear_count in sender_swear_counts.items():
        total_count = sender_message_counts.get(member_id, 0)
        if total_count <= 0:
            continue
        meta = sender_meta.get(member_id, {})
        rate = round((swear_count / total_count) * 100, 2)
        top_swearers.append({
            "id": str(member_id),
            "name": meta.get("name", "Unknown"),
            "avatar_url": meta.get("avatar_url"),
            "swear_messages": swear_count,
            "message_count": total_count,
            "swear_rate": rate,
        })

    top_swearers.sort(key=lambda item: (item["swear_rate"], item["swear_messages"], item["message_count"]), reverse=True)
    top_swearers = top_swearers[:top_n]

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

        "top_swearers": top_swearers,

        "spotlight_mentions": build_spotlight_mentions(mention_counts),

        "keyword_buckets": {
            bucket: {
                "count":   bucket_counts[bucket],
                "weighted_count": round(bucket_weighted[bucket], 2),
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

    apply_vote_results_to_stats(stats, guild)

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


@bot.group(name="wrapped", invoke_without_command=True)
@commands.has_permissions(manage_messages=True)
async def wrapped_cmd(ctx: commands.Context, subcommand: str = ""):
    """
    !wrapped          → full scrape + write stats.json
    !wrapped status   → quick message count per channel
    !wrapped preview  → scrape + post a summary embed (no file write)
    """

    await _send_watching_dm(ctx)
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


@wrapped_cmd.command(name="vote")
@commands.guild_only()
async def vote_cmd(ctx: commands.Context, action: str = None, member: discord.Member = None):
    """
    !wrapped vote <category> @member   → cast a vote
    !wrapped vote categories           → list available categories
    !wrapped vote results              → show current winners
    """

    await _send_watching_dm(ctx)

    if not VOTE_CATEGORIES:
        await ctx.send("⚠️ No vote categories are configured yet.")
        return

    if not action:
        await _send_vote_panel_in_server(ctx)
        return

    action_key = _slugify(action)

    if action_key in {"categories", "category", "list"}:
        await vote_categories_cmd(ctx)
        return

    if action_key in {"results", "result", "winners"}:
        await vote_results_cmd(ctx)
        return

    if action_key in {"menu", "panel", "gui"}:
        await _send_vote_panel_in_server(ctx)
        return

    resolved = _resolve_vote_category(action)
    if not resolved:
        await ctx.send(
            "❌ Unknown vote category. Use `!wrapped vote categories` to see the available options."
        )
        return

    if member is None:
        await _send_vote_panel_in_server(ctx, preselected_category=resolved)
        return

    confirmation = await _save_vote(ctx.guild, ctx.author, resolved, member)
    with suppress(discord.Forbidden, discord.HTTPException):
        await ctx.message.delete()
    await _send_private_vote_ack(ctx, confirmation)


@commands.guild_only()
async def vote_categories_cmd(ctx: commands.Context):
    if not VOTE_CATEGORIES:
        await ctx.send("⚠️ No vote categories are configured yet.")
        return

    lines = ["🗳️ **Vote categories**"]
    for key, meta in VOTE_CATEGORIES.items():
        emoji = meta.get("emoji") or "🗳️"
        label = meta.get("label") or key.replace("_", " ").title()
        desc = meta.get("description") or ""
        lines.append(f"• {emoji} `{key}` — {label}{f' · {desc}' if desc else ''}")
    if len(VOTE_CATEGORIES) > 25:
        lines.append("\n⚠️ The interactive menu only shows the first 25 categories. Use the text form for the rest.")
    lines.append("\nUse: `!wrapped vote <category_key> @member`")
    await ctx.send("\n".join(lines))


@commands.guild_only()
async def vote_results_cmd(ctx: commands.Context):
    store = load_vote_store()
    results = build_vote_results(ctx.guild, store)

    if not results:
        await ctx.send("No vote categories are configured yet.")
        return

    lines = ["📊 **Current vote results**"]
    any_votes = False
    for item in results:
        if not item["winners"]:
            lines.append(f"• {item['label']}: no votes yet")
            continue
        any_votes = True
        winner_names = ", ".join(w["name"] for w in item["winners"])
        lines.append(f"• {item['label']}: **{winner_names}** ({item['vote_count']} votes)")

    if not any_votes:
        lines.append("\nNo votes have been cast yet.")

    await ctx.send("\n".join(lines))


async def _send_vote_help(ctx: commands.Context):
    lines = ["🗳️ **How voting works**"]
    lines.append("• Run `!wrapped vote` to open the interactive voting panel in this server")
    lines.append("• Or use `!wrapped vote <category_key> @member` for text voting")
    lines.append("• Vote choices and confirmations are private to you")
    lines.append("• List categories with `!wrapped vote categories`")
    lines.append("• View current winners with `!wrapped vote results`")
    if VOTE_CATEGORIES:
        lines.append("\nCurrent categories:")
        for key, meta in VOTE_CATEGORIES.items():
            emoji = meta.get("emoji") or "🗳️"
            label = meta.get("label") or key.replace("_", " ").title()
            lines.append(f"• {emoji} `{key}` — {label}")
    await ctx.send("\n".join(lines))


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

    if stats.get("top_swearers"):
        top_swearer = stats["top_swearers"][0]
        embed.add_field(
            name="😈 Top Swearer",
            value=f"**{top_swearer['name']}** — {top_swearer['swear_rate']:.1f}% of messages",
            inline=False,
        )

    top3 = ", ".join(
        f"**{s['name']}** ({s['count']:,})"
        for s in stats["top_senders"][:3]
    )
    embed.add_field(name="🏆 Top Senders",  value=top3 or "—",  inline=False)

    top3e = "  ".join(s["emoji"] for s in stats["top_emojis"][:5])
    embed.add_field(name="🔥 Top Emojis",  value=top3e or "—", inline=False)

    vote_results = [item for item in stats.get("as_voted_by_you", []) if item.get("winners")]
    if vote_results:
        vote_lines = []
        for item in vote_results[:3]:
            winner = item["winners"][0]
            vote_lines.append(f"**{item['label']}** → {winner['name']}")
        embed.add_field(name="🗳️ Votes", value="\n".join(vote_lines), inline=False)

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
