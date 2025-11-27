from discord.ext import commands
import discord
import asyncio
from yt_dlp import YoutubeDL
import functools
import spotipy
from spotipy.oauth2 import SpotifyClientCredentials
import os
import re
import validators
import sys

# YoutubeDL options for audio extraction
YDL_OPTIONS = {
    'format': 'bestaudio/best',
    'noplaylist': True,
    'default_search': 'ytsearch',
    'quiet': True,
    'nocheckcertificate': True,
    'ignoreerrors': True,
    'logtostderr': False,
    'extractaudio': True,
    'audioformat': 'mp3',
    'outtmpl': '%(extractor)s-%(id)s-%(title)s.%(ext)s',
    'restrictfilenames': True,
    'buffersize': 1024 * 16, # 16KiB
    'extractor_args': {'youtube': {'player_client': 'default'}}
}

FFMPEG_OPTIONS = {
    'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5',
    'options': '-vn' # no video
}

class MusicControlView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Pause", style=discord.ButtonStyle.secondary, emoji="⏸️", custom_id="pause_resume")
    async def pause_resume(self, interaction: discord.Interaction, button: discord.ui.Button):
        music_cog = interaction.client.get_cog('Music')
        vc = interaction.guild.voice_client
        if not vc:
            return await interaction.response.send_message("I'm not in a voice channel.", ephemeral=True)

        if vc.is_playing():
            vc.pause()
            button.label = "Resume"
            button.emoji = "▶️"
            await interaction.response.edit_message(view=self)
        elif vc.is_paused():
            vc.resume()
            button.label = "Pause"
            button.emoji = "⏸️"
            await interaction.response.edit_message(view=self)
        else:
            await interaction.response.send_message("Not playing anything.", ephemeral=True)

    @discord.ui.button(label="Skip", style=discord.ButtonStyle.primary, emoji="⏭️", custom_id="skip")
    async def skip(self, interaction: discord.Interaction, button: discord.ui.Button):
        vc = interaction.guild.voice_client
        if not vc or not (vc.is_playing() or vc.is_paused()):
            return await interaction.response.send_message("Not playing anything to skip.", ephemeral=True)
        
        vc.stop()
        await interaction.response.defer()

    @discord.ui.button(label="Stop", style=discord.ButtonStyle.danger, emoji="⏹️", custom_id="stop")
    async def stop(self, interaction: discord.Interaction, button: discord.ui.Button):
        music_cog = interaction.client.get_cog('Music')
        guild_id = interaction.guild_id
        vc = interaction.guild.voice_client
        if not vc:
            return await interaction.response.send_message("I'm not in a voice channel.", ephemeral=True)

        if guild_id in music_cog.music_queue:
            music_cog.music_queue[guild_id].clear()
        
        music_cog.is_playing[guild_id] = False
        music_cog.current_song[guild_id] = None

        if vc.is_playing() or vc.is_paused():
            vc.stop()

        if music_cog.now_playing_message.get(guild_id):
            try:
                await music_cog.now_playing_message[guild_id].edit(content="Playback stopped.", view=None)
            except discord.NotFound:
                pass
            music_cog.now_playing_message[guild_id] = None
        
        await interaction.response.defer()

    @discord.ui.button(label="Queue", style=discord.ButtonStyle.secondary, emoji="📜", custom_id="queue")
    async def queue(self, interaction: discord.Interaction, button: discord.ui.Button):
        music_cog = interaction.client.get_cog('Music')
        guild_id = interaction.guild_id
        
        if not music_cog.music_queue.get(guild_id) and not music_cog.is_playing.get(guild_id):
            return await interaction.response.send_message("The queue is currently empty.", ephemeral=True)

        queue_list = []
        if music_cog.is_playing.get(guild_id) and music_cog.current_song.get(guild_id):
            queue_list.append(f"Now Playing: {music_cog.current_song[guild_id]['name']}")
        
        for i, song in enumerate(music_cog.music_queue.get(guild_id, [])):
            queue_list.append(f"{i+1}. {song['name']}")
        
        if queue_list:
            await interaction.response.send_message("```\n" + "\n".join(queue_list) + "\n```", ephemeral=True)
        else:
            await interaction.response.send_message("The queue is empty.", ephemeral=True)

class Music(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.music_queue = {} # Guild ID -> list of songs
        self.is_playing = {} # Guild ID -> boolean
        self.current_song = {} # Guild ID -> current song
        self.now_playing_message = {} # Guild ID -> message object
        # Spotify API Setup - Client Credentials Flow (for public data like track search)
        self.sp = spotipy.Spotify(auth_manager=SpotifyClientCredentials(
            client_id=os.getenv("SPOTIPY_CLIENT_ID"),
            client_secret=os.getenv("SPOTIPY_CLIENT_SECRET")
        ))
        
    def _search_youtube(self, query):
        with YoutubeDL(YDL_OPTIONS) as ydl:
            try:
                info = ydl.extract_info(f"ytsearch:{query}", download=False)['entries'][0]
                return {
                    'url': info['url'],
                    'web_url': info['webpage_url'],
                    'thumbnail': info.get('thumbnail'),
                    'duration': info.get('duration'),
                }
            except Exception:
                return None