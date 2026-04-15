# ╔══════════════════════════════════════════════════════════════╗
# ║              SERVER WRAPPED — BOT CONFIGURATION             ║
# ║  Edit everything in this file. Nothing else needs changing. ║
# ╚══════════════════════════════════════════════════════════════╝

CONFIG = {

    # ── SERVER / CHANNEL SETTINGS ──────────────────────────────────
    # Leave CHANNEL_IDS empty [] to scrape ALL channels
    # Or add specific channel IDs as strings: ["123456789", "987654321"]
    "CHANNEL_IDS": [],

    # Channels to always skip (by name fragment, lowercase)
    "EXCLUDE_CHANNELS": ["rules", "announcements", "welcome", "bot-commands"],

    # Date range to analyse (ISO format "YYYY-MM-DD", or None for no limit)
    "DATE_FROM": "2024-09-01",
    "DATE_TO":   None,   # None = up to today

    # ── PEOPLE TO SPOTLIGHT ────────────────────────────────────────
    # These get their own mention counter on the recap page
    "SPOTLIGHT_NAMES": [
        "noel",
        "dr noel",
    ],

    # ── MIDNIGHT ZONE ─────────────────────────────────────────────
    # Questions or messages sent in this hour range get counted separately
    # Uses the server timezone (UTC by default — adjust TIMEZONE below)
    "MIDNIGHT_ZONE_START": 2,   # 2am
    "MIDNIGHT_ZONE_END":   6,   # 6am
    "TIMEZONE": "Europe/Dublin",

    # ── KEYWORD BUCKETS ───────────────────────────────────────────
    # Each bucket gets its own counter + example messages on the recap page
    # Keys become section titles (formatted automatically)
    "KEYWORD_BUCKETS": {

        "panic_deadline": [
            "deadline", "due tonight", "due tomorrow", "help me",
            "im screwed", "i'm screwed", "we're cooked", "were cooked",
            "last minute", "all nighter", "all-nighter", "haven't started",
            "havent started", "not done", "not finished", "running out of time",
        ],

        "noel_mentions": [
            "noel", "dr noel", "that lecturer", "the lecturer",
        ],

        "dark_humor": [
            "kys", "kms", "kill yourself", "kill myself",
            "end it", "i want to die", "want to die",
            "unalive", "off myself",
        ],

        "violence_jokes": [
            "beat him up", "beat her up", "beat them up",
            "fight him", "fight her", "want to fight",
            "gonna fight", "going to fight", "smack", "batter",
            "lamp him", "lamp her", "clatter",
        ],

        "cope_messages": [
            "i'm fine", "im fine", "everything is fine",
            "its fine", "it's fine", "don't panic", "dont panic",
            "totally fine", "completely fine", "absolutely fine",
        ],

        "classic_excuses": [
            "the wifi was down", "my laptop died", "i forgot",
            "thought it was friday", "thought it was next week",
            "wrong branch", "wrong file", "corrupted",
            "github ate my", "lost my work",
        ],
    },

    # ── TOP N LIMITS ──────────────────────────────────────────────
    "TOP_SENDERS_COUNT":  10,
    "TOP_EMOJIS_COUNT":   10,
    "TOP_CHANNELS_COUNT": 8,
    "SAMPLE_MESSAGES":    5,   # How many example messages to save per bucket

    # ── OUTPUT ────────────────────────────────────────────────────
    # Path to write stats.json (relative to bot.py location)
    # Point this at your web/ folder so Vercel picks it up automatically
    "OUTPUT_PATH": "../web/stats.json",

}
