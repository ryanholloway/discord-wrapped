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
    "EXCLUDE_CHANNELS": ["rules", "welcome", "bot-commands", "hello-there", "test", "log", "stuff", "transcripts", "roles", "who-are-you", "ticket-creation"],

    # Date range to analyse (ISO format "YYYY-MM-DD", or None for no limit)
    "DATE_FROM": "2022-09-01",
    "DATE_TO":   None,   # None = up to today

    # ── PEOPLE TO SPOTLIGHT ────────────────────────────────────────
    # These get their own mention counter on the recap page
    "SPOTLIGHT_NAMES": [
        "noel",
        "dr noel",
        "noel o'hara",
        "o'hara"
    ],

    # ── MIDNIGHT ZONE ─────────────────────────────────────────────
    # Questions or messages sent in this hour range get counted separately
    # Uses the server timezone (UTC by default — adjust TIMEZONE below)
    "MIDNIGHT_ZONE_START": 1,   # 1am
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
            "time is running out", "time's running out", "so much to do", "overwhelmed",
            "drowning in work", "swamped", "up to my neck", "up to my eyeballs",
        ],

        "noel_mentions": [
            "noel", "noel o'hara", "that lecturer", "the lecturer", "that dickhead", "that asshole", "o'hara",
        ],
        
        "phil_mentions": [
            "phil", "philomena", "that tutor", "the tutor", "philip", "philip bourke", "that dickhead", "that asshole",
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
            "totally fine", "completely fine", "absolutely fine", "fine actually"
        ],

        "classic_excuses": [
            "the wifi was down", "my laptop died",
            "thought it was due", "thought it was next week",
            "wrong branch", "wrong file", "corrupted",
            "github ate my", "lost my work", "computer ate my", "computer ate it"
        ],
        
        "swear_words": [
            "fuck", "shit", "bitch", "asshole", "dick", "bastard", "slut", "retard", "cunt", "fucker", "ass", "cock"
        ],
        
        "procrastination": [
            "procrastinating", "procrastinate", "procrastination",
            "distracted", "distracting", "distraction",
            "can't focus", "cant focus", "cannot focus",
            "lost motivation", "no motivation",
        ],
        
        "ai_mentions": [
            "chatgpt", "gpt-4", "gpt-3.5", "bard", "gemini", "ai wrote",
            "ai-generated", "ai generated", "artificial intelligence", "claude", "chatgpt wrote",
            "chatgpt-generated", "chatgpt generated", "AI wrote this", "AI-generated", "AI generated",
        ],
        
       "stress_indicators": [
            "stressed", "stress", "overwhelmed", "anxious", "panic attack",
            "burned out", "burnt out", "exhausted", "sleepless",
            "can't sleep", "cant sleep", "insomnia"
        ],
       
       "party_time": [
            "party", "partying", "rave", "raving", "lit", "turn up",
            "turn-up", "turnup", "going out", "gonna go out", "going to go out",
            "weekend vibes", "friday night vibes"
        ],
       
       "drink_mentions": [
            "beer", "wine", "vodka", "whiskey", "rum", "tequila", "gin", "cocktail", "drunk", "getting drunk", "gonna get drunk",
            "going to get drunk", "drinking tonight", "drinking this weekend"
        ], 
       
       "gaming_references": [
            "gaming", "gamer", "video games", "playstation", "xbox", "nintendo", "pc gaming",
            "steam", "epic games", "fortnite", "call of duty", "league of legends",
            "world of warcraft", "among us", "minecraft"
        ],
    },

    # ── TOP N LIMITS ──────────────────────────────────────────────
    "TOP_SENDERS_COUNT":  10,
    "TOP_EMOJIS_COUNT":   10,
    "TOP_CHANNELS_COUNT": 10,
    "SAMPLE_MESSAGES":    15,   # How many example messages to save per bucket

    # ── OUTPUT ────────────────────────────────────────────────────
    # Path to write stats.json (relative to bot.py location)
    # Point this at your web/ folder so Vercel picks it up automatically
    "OUTPUT_PATH": "../web/stats.json",

}
