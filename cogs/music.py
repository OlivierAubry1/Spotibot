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
}

FFMPEG_OPTIONS = {
    'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5',
    'options': '-vn' # no video
}

class Music(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.music_queue = {} # Guild ID -> list of songs
        self.is_playing = {} # Guild ID -> boolean
        self.current_song = {} # Guild ID -> current song
        # Spotify API Setup - Client Credentials Flow (for public data like track search)
        self.sp = spotipy.Spotify(auth_manager=SpotifyClientCredentials(
            client_id=os.getenv("SPOTIPY_CLIENT_ID"),
            client_secret=os.getenv("SPOTIPY_CLIENT_SECRET")
        ))
        
    def _search_youtube(self, query):
        with YoutubeDL(YDL_OPTIONS) as ydl:
            try:
                info = ydl.extract_info(f"ytsearch:{query}", download=False)['entries'][0]
                return info['url']
            except Exception:
                return None

    def _get_info_from_youtube_url(self, url):
        with YoutubeDL(YDL_OPTIONS) as ydl:
            try:
                info = ydl.extract_info(url, download=False)
                return {
                    'name': info.get('title', 'Unknown Title'),
                    'url': info.get('url'),
                }
            except Exception:
                return None

    async def _get_song_info(self, query):
        """
        Determines the type of query and returns a list of songs and a message.
        A song is a dictionary with 'name' and 'url'.
        """
        songs = []
        loop = asyncio.get_event_loop()
        message = ""

        if validators.url(query):
            if 'spotify.com' in query:
                if 'track' in query:
                    try:
                        track_id = query.split('/')[-1].split('?')[0]
                        track = self.sp.track(track_id)
                        song_name = f"{track['artists'][0]['name']} - {track['name']}"
                        yt_url = await loop.run_in_executor(None, lambda: self._search_youtube(song_name))
                        if yt_url:
                            songs.append({'name': song_name, 'url': yt_url})
                        message = f"Added '{song_name}' to the queue."
                    except Exception as e:
                        print(f"Error processing spotify track url: {e}") # Log error
                        return None, f"Could not get Spotify track information: {e}"
                elif 'playlist' in query:
                    try:
                        playlist_id = query.split('/')[-1].split('?')[0]
                        results = self.sp.playlist_tracks(playlist_id)
                        tracks = results['items']
                        while results['next']:
                            results = self.sp.next(results)
                            tracks.extend(results['items'])

                        for item in tracks:
                            track = item.get('track')
                            if track:
                                song_name = f"{track['artists'][0]['name']} - {track['name']}"
                                yt_url = await loop.run_in_executor(None, lambda: self._search_youtube(song_name))
                                if yt_url:
                                    songs.append({'name': song_name, 'url': yt_url})
                        message = f"Added {len(songs)} songs to the queue."
                    except Exception as e:
                        print(f"Error processing spotify playlist url: {e}")
                        return None, f"Could not get Spotify playlist information: {e}"
            else: # Other URLs (assume YouTube)
                try:
                    info = await loop.run_in_executor(None, lambda: self._get_info_from_youtube_url(query))
                    if info:
                        songs.append(info)
                        message = f"Added '{info['name']}' to the queue."
                except Exception as e:
                    print(f"Error processing youtube url: {e}")
                    return None, "Error processing YouTube link."
        else: # It's a search query
            try:
                results = self.sp.search(q=query, type='track', limit=1)
                if not results['tracks']['items']:
                    return None, f"Could not find any songs matching '{query}' on Spotify."
                track = results['tracks']['items'][0]
                song_name = f"{track['artists'][0]['name']} - {track['name']}"
                yt_url = await loop.run_in_executor(None, lambda: self._search_youtube(song_name))
                if yt_url:
                    songs.append({'name': song_name, 'url': yt_url})
                    message = f"Added '{song_name}' to the queue."
            except Exception as e:
                print(f"Error searching spotify: {e}")
                return None, "An error occurred while searching Spotify."
        
        if not songs:
            return None, "Could not find a playable song for your query."

        return songs, message

    # Function to play the next song in the queue
    async def play_next(self, ctx):
        guild_id = ctx.guild.id
        if not self.music_queue.get(guild_id):
            self.is_playing[guild_id] = False
            self.current_song[guild_id] = None
            if ctx.voice_client and ctx.voice_client.is_connected():
                await asyncio.sleep(60) # Wait a bit before disconnecting
                if not self.is_playing.get(guild_id) and not self.music_queue.get(guild_id):
                    await ctx.voice_client.disconnect()
            return

        song = self.music_queue[guild_id].pop(0)
        self.current_song[guild_id] = song # Set the current playing song

        await ctx.channel.send(f"Now playing: {song['name']}")

        try:
            source = discord.FFmpegPCMAudio(song['url'], **FFMPEG_OPTIONS)
            ctx.voice_client.play(source, after=lambda e: self.bot.loop.call_soon_threadsafe(functools.partial(asyncio.create_task, self.play_next(ctx))))
        except Exception as e:
            await ctx.channel.send(f"Error playing song: {song['name']} - {e}")
            self.is_playing[guild_id] = False
            await self.play_next(ctx) # Try to play next song if error occurs

    @commands.command(name='join', help='Tells the bot to join the voice channel')
    async def join(self, ctx):
        if not ctx.author.voice:
            await ctx.send("You are not connected to a voice channel.")
            return
        
        channel = ctx.author.voice.channel
        await channel.connect()
        await ctx.send(f"Joined {channel.name}!")

    @commands.command(name='leave', help='To make the bot leave the voice channel')
    async def leave(self, ctx):
        if not ctx.voice_client:
            await ctx.send("I am not in a voice channel.")
            return
        
        await ctx.voice_client.disconnect()
        await ctx.send("Left the voice channel.")

    @commands.command(name='refresh', help='Kills bot process to refresh memory and creates a new one')
    async def refresh(self, ctx):
            await ctx.send("Be right back! Refreshing...")
            sys.exit()
            return
        
        

    @commands.command(name='play', help='To play song')
    async def play(self, ctx, *, query: str = None):
        guild_id = ctx.guild.id
        if guild_id not in self.music_queue:
            self.music_queue[guild_id] = []
            self.is_playing[guild_id] = False
            self.current_song[guild_id] = None

        if not ctx.author.voice:
            await ctx.send("You need to be in a voice channel to play music!")
            return

        if not query:
            await ctx.send("Please provide a song name or a URL.")
            return

        if not ctx.voice_client:
            try:
                channel = ctx.author.voice.channel
                await channel.connect()
                await ctx.send(f"Joined {channel.name} to play music.")
            except Exception as e:
                await ctx.send(f"Could not join the voice channel: {e}")
                return

        await ctx.send("Searching...")
        
        songs, message = await self._get_song_info(query)

        if not songs:
            await ctx.send(message)
            return

        for song in songs:
            song['guild_id'] = guild_id
            song['channel_id'] = ctx.channel.id
            self.music_queue[guild_id].append(song)
        
        await ctx.send(message)

        if not self.is_playing.get(guild_id):
            self.is_playing[guild_id] = True
            await self.play_next(ctx)

    @commands.command(name='queue', help='Displays the current song queue')
    async def queue(self, ctx):
        guild_id = ctx.guild.id
        if not self.music_queue.get(guild_id) and not self.is_playing.get(guild_id):
            await ctx.send("The queue is currently empty.")
            return

        queue_list = []
        if self.is_playing.get(guild_id) and self.current_song.get(guild_id):
            queue_list.append(f"Now Playing: {self.current_song[guild_id]['name']}")
        
        for i, song in enumerate(self.music_queue[guild_id]):
            queue_list.append(f"{i+1}. {song['name']}")
        
        if queue_list:
            await ctx.send("```\n" + "\n".join(queue_list) + "\n```")
        else:
            await ctx.send("The queue is empty.")

    @commands.command(name='skip', help='Skips the current song')
    async def skip(self, ctx):
        guild_id = ctx.guild.id
        if not ctx.voice_client or not ctx.voice_client.is_playing():
            await ctx.send("No music is currently playing to skip.")
            return
        
        ctx.voice_client.stop() # This will trigger the `after` callback and play the next song
        await ctx.send("Skipped the current song.")

    @commands.command(name='stop', help='Stops playback and clears the queue')
    async def stop(self, ctx):
        guild_id = ctx.guild.id
        if not ctx.voice_client:
            await ctx.send("I am not in a voice channel.")
            return

        if guild_id in self.music_queue:
            self.music_queue[guild_id].clear()
        
        self.is_playing[guild_id] = False
        self.current_song[guild_id] = None

        if ctx.voice_client.is_playing() or ctx.voice_client.is_paused():
            ctx.voice_client.stop()
        elif ctx.voice_client.is_connected():
            await ctx.voice_client.disconnect()

        await ctx.send("Stopped playback and cleared the queue.")

    @commands.command(name='pause', help='Pauses the current song')
    async def pause(self, ctx):
        if ctx.voice_client and ctx.voice_client.is_playing():
            ctx.voice_client.pause()
            await ctx.send("Playback paused.")
        else:
            await ctx.send("No music is currently playing.")
            
    @commands.command(name='resume', help='Resumes the paused song')
    async def resume(self, ctx):
        if ctx.voice_client and ctx.voice_client.is_paused():
            ctx.voice_client.resume()
            await ctx.send("Playback resumed.")
        else:
            await ctx.send("No music is currently paused.")

    @commands.command(name='nowplaying', aliases=['np'], help='Shows information about the currently playing song')
    async def nowplaying(self, ctx):
        guild_id = ctx.guild.id
        if self.current_song.get(guild_id) and ctx.voice_client and ctx.voice_client.is_playing():
            await ctx.send(f"Now playing: {self.current_song[guild_id]['name']}")
        elif self.current_song.get(guild_id) and ctx.voice_client and ctx.voice_client.is_paused():
            await ctx.send(f"Currently paused: {self.current_song[guild_id]['name']}")
        else:
            await ctx.send("No music is currently playing.")

    @commands.Cog.listener()
    async def on_command_error(self, ctx, error):
        if isinstance(error, commands.MissingRequiredArgument):
            await ctx.send("Please provide all required arguments for the command.")
        elif isinstance(error, commands.CommandNotFound):
            pass # Ignore unknown commands
        elif isinstance(error, commands.MissingPermissions):
            await ctx.send("You don't have the necessary permissions to use this command.")
        else:
            await ctx.send(f"An error occurred: {error}")
            print(f"Error in command {ctx.command}: {error}")

async def setup(bot):
    await bot.add_cog(Music(bot))