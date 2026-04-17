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
    "EXCLUDE_CHANNELS": ["counting", "rules", "welcome", "bot-commands", "hello-there", "test", "log", "stuff", "transcripts", "roles", "who-are-you", "ticket-creation"],

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

    # ── VOTING CATEGORIES ─────────────────────────────────────────
    # Used by the !vote commands.
    # Key = command slug, value = display label + optional emoji/description.
    "VOTE_CATEGORIES": {
        "most_likely_to_be_late": {
            "label": "Most Likely to Be Late",
            "emoji": "⏰",
            "description": "Vote for the person who is always cutting it close.",
        },
        "most_likely_to_forget_the_deadline": {
            "label": "Most Likely to Forget the Deadline",
            "emoji": "📚",
            "description": "Vote for the person who would absolutely miss a due date.",
        },
        "most_likely_to_carry_the_group": {
            "label": "Most Likely to Carry the Group",
            "emoji": "🏋️",
            "description": "Vote for the person doing the most lifting.",
        },
        "most_likely_to_have_a_breakdown": {
            "label": "Most Likely to Have a Breakdown",
            "emoji": "💥",
            "description": "Vote for the person who is most likely to have a breakdown.",
        },
        "most_likely_to_be_drunk_during_a_group_meeting": {
            "label": "Most Likely to Be Drunk During a Group Meeting",
            "emoji": "🍻",
            "description": "Vote for the person who is most likely to be drunk during a group meeting.",
        },
        "most_likely_to_be_a_pedo": {
            "label": "Most Likely to be a Pedo",
            "emoji": "👶",
            "description": "Vote for the person who is most likely to be a pedo. (idk man, Kyle Requested this one, ask him)",
        },
        "most_likely_to_be_AI": {
            "label": "Most Likely to be an AI",
            "emoji": "🤖",
            "description": "Vote for the person who is most likely to be an AI.",
        },
        "most_likely_to_go_to_epsteins_island_but_for_the_snorkling_and_not_the_other_stuff": {
            "label": "Most Likely to go to Epstein's Island but for the Snorkeling and not the other stuff",
            "emoji": "🏝️",
            "description": "Vote for the person who is most likely to go to Epstein's Island but for the Snorkeling and not the other stuff.",
        },
        "most_likely_to_die_to_a_chatGPT_generated_message": {
            "label": "Most Likely to Die to a ChatGPT-Generated Message",
            "emoji": "💀",
            "description": "Vote for the person who is most likely to die to a ChatGPT-generated message.",
        },
        "most_likely_to_be_caught_using_chatGPT_on_an_assignment": {
            "label": "Most Likely to be Caught Using ChatGPT on an Assignment",
            "emoji": "👀",
            "description": "Vote for the person who is most likely to be caught using ChatGPT on an assignment.",
        },
        "most_likely_to_be_a_russian_spy": {
            "label": "Most Likely to be a Russian Spy",
            "emoji": "🇷🇺",
            "description": "Vote for the person who is most likely to be a Russian spy.",
        },
        "most_likely_to_develop_a_crush_on_the_lecturer": {
            "label": "Most Likely to Develop a Crush on the Lecturer",
            "emoji": "😍",
            "description": "Vote for the person who is most likely to develop a crush on the lecturer.",
        },
        "most_likely_to_slime_out_a_lecturer": {
            "label": "Most Likely to Slime Out a Lecturer",
            "emoji": "🤢",
            "description": "Vote for the person who is most likely to slime out a lecturer.",
        }
    },

    # ── MIDNIGHT ZONE ─────────────────────────────────────────────
    # Questions or messages sent in this hour range get counted separately
    # Uses the server timezone (UTC by default — adjust TIMEZONE below)
    "MIDNIGHT_ZONE_START": 1,   # 1am
    "MIDNIGHT_ZONE_END":   6,   # 6am
    "TIMEZONE": "Europe/Dublin",

    # ── KEYWORD BUCKETS ───────────────────────────────────────────
    # Each bucket gets its own counter + example messages on the recap page
    # Keys become section titles (formatted automatically)
    # Matching is whole-word/phrase by default (to avoid false positives).
    # Add terms to KEYWORD_SUBSTRING_MATCH below to match them inside larger words.
    "KEYWORD_SUBSTRING_MATCH": [
        "shit",     # Acceptable inside: bullshit, shitty, etc.
    ],

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

        "cope_messages": [
            "i'm fine", "im fine", "everything is fine",
            "its fine", "it's fine", "don't panic", "dont panic",
            "totally fine", "completely fine", "absolutely fine", "fine actually"
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
