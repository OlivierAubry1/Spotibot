import discord
from discord.ext import commands
import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
SPOTIPY_CLIENT_ID = os.getenv("SPOTIPY_CLIENT_ID")
SPOTIPY_CLIENT_SECRET = os.getenv("SPOTIPY_CLIENT_SECRET")

# --- Discord Bot Setup ---
intents = discord.Intents.default()
intents.message_content = True  # Enable message content intent
intents.voice_states = True     # Enable voice state intent for joining/leaving voice channels
bot = commands.Bot(command_prefix='!', intents=intents)

try:
    bot.load_extension("cogs.music")
except Exception as e:
    print(f"Failed to load extension cogs.music: {e}")
    raise

# Run the bot
if __name__ == "__main__":
    if DISCORD_TOKEN is None:
        print("Error: DISCORD_TOKEN not found in .env file.")
    elif SPOTIPY_CLIENT_ID is None or SPOTIPY_CLIENT_SECRET is None:
        print("Error: SPOTIPY_CLIENT_ID or SPOTIPY_CLIENT_SECRET not found in .env file.")
    else:
        bot.run(DISCORD_TOKEN)