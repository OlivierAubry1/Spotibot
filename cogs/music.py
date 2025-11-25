from discord.ext import commands
import discord
import asyncio
from yt_dlp import YoutubeDL
import functools
import spotipy
from spotipy.oauth2 import SpotifyClientCredentials
import os

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
        
    # Helper function to get YouTube URL from spotify track name
    def get_youtube_url_from_spotify_track(self, query):
        with YoutubeDL(YDL_OPTIONS) as ydl:
            try:
                info = ydl.extract_info(f"ytsearch:{query}", download=False)['entries'][0]
                return info['url']
            except Exception:
                return None

    # Function to play the next song in the queue
    async def play_next(self, ctx):
        guild_id = ctx.guild.id
        if not self.music_queue.get(guild_id):
            self.is_playing[guild_id] = False
            self.current_song[guild_id] = None
            if ctx.voice_client and ctx.voice_client.is_connected():
                await ctx.voice_client.disconnect()
            return

        song = self.music_queue[guild_id].pop(0)
        self.current_song[guild_id] = song # Set the current playing song

        if ctx.channel:
            await ctx.channel.send(f"Now playing: {song['name']}")

        try:
            source = discord.FFmpegPCMAudio(song['url'], **FFMPEG_OPTIONS)
            ctx.voice_client.play(source, after=lambda e: self.bot.loop.call_soon_threadsafe(functools.partial(asyncio.create_task, self.play_next(ctx))))
        except Exception as e:
            if ctx.channel:
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
            await ctx.send("Please provide a song name or a Spotify link.")
            return

        # Attempt to join the voice channel if not already in one
        if not ctx.voice_client:
            channel = ctx.author.voice.channel
            await channel.connect()
            await ctx.send(f"Joined {channel.name} to play music.")
        
        # Determine if it's a Spotify URL or a search query
        track_info = None
        if "spotify.com/track/" in query:
            try:
                track_id = query.split('/')[-1].split('?')[0]
                track = self.sp.track(track_id)
                track_info = {
                    'artist': track['artists'][0]['name'],
                    'title': track['name']
                }
                song_name = f"{track_info['artist']} - {track_info['title']}"
            except Exception as e:
                await ctx.send(f"Could not get Spotify track information: {e}")
                return
        elif "spotify.com/playlist/" in query:
            try:
                playlist_id = query.split('/')[-1].split('?')[0]
                results = self.sp.playlist_tracks(playlist_id)
                tracks = results['items']
                while results['next']:
                    results = self.sp.next(results)
                    tracks.extend(results['items'])

                if not tracks:
                    await ctx.send("The Spotify playlist is empty or could not be accessed.")
                    return

                await self.add_tracks_to_queue(ctx, tracks)
                return # Stop further execution for playlists
            except Exception as e:
                await ctx.send(f"Could not get Spotify playlist information: {e}")
                return
        else:
            # Search Spotify for the track
            try:
                results = self.sp.search(q=query, type='track', limit=1)
                if not results['tracks']['items']:
                    await ctx.send(f"Could not find any songs matching '{query}' on Spotify.")
                    return
                track = results['tracks']['items'][0]
                track_info = {
                    'artist': track['artists'][0]['name'],
                    'title': track['name']
                }
                song_name = f"{track_info['artist']} - {track_info['title']}"
            except Exception as e:
                await ctx.send(f"An error occurred while searching Spotify: {e}")
                return

        await ctx.send(f"Searching for '{song_name}'...")

        # Get YouTube URL
        loop = asyncio.get_event_loop()
        try:
            # Use run_in_executor for blocking operations like yt-dlp
            yt_url = await loop.run_in_executor(None, lambda: self.get_youtube_url_from_spotify_track(song_name))
            if not yt_url:
                await ctx.send(f"Could not find a YouTube link for '{song_name}'.")
                return
        except Exception as e:
            await ctx.send(f"An error occurred while fetching YouTube link: {e}")
            return

        # Add to queue
        new_song_data = {
            'name': song_name,
            'url': yt_url,
            'guild_id': ctx.guild.id,
            'channel_id': ctx.channel.id
        }
        self.music_queue[guild_id].append(new_song_data)
        
        if not self.is_playing[guild_id]:
            self.is_playing[guild_id] = True
            self.current_song[guild_id] = new_song_data # Set current song immediately if nothing is playing
            await self.play_next(ctx)
        else:
            await ctx.send(f"Added '{song_name}' to the queue. Position: {len(self.music_queue[guild_id])}")

    async def add_tracks_to_queue(self, ctx, tracks):
        """Helper function to process and queue multiple tracks."""
        guild_id = ctx.guild.id
        await ctx.send(f"Adding {len(tracks)} songs from the playlist to the queue...")

        for item in tracks:
            track = item.get('track')
            if not track:
                continue

            song_name = f"{track['artists'][0]['name']} - {track['name']}"
            
            loop = asyncio.get_event_loop()
            try:
                yt_url = await loop.run_in_executor(None, lambda: self.get_youtube_url_from_spotify_track(song_name))
                if yt_url:
                    new_song_data = {
                        'name': song_name,
                        'url': yt_url,
                        'guild_id': guild_id,
                        'channel_id': ctx.channel.id
                    }
                    self.music_queue[guild_id].append(new_song_data)
            except Exception:
                await ctx.send(f"Skipping '{song_name}' as a YouTube link could not be found.")

        if not self.is_playing.get(guild_id):
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