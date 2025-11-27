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

        message = music_cog.now_playing_message.get(guild_id)
        if message:
            try:
                await message.edit(content="Playback stopped.", embed=None, view=None)
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
    def _get_info_from_youtube_url(self, url):
        with YoutubeDL(YDL_OPTIONS) as ydl:
            try:
                info = ydl.extract_info(url, download=False)
                return {
                    'name': info.get('title', 'Unknown Title'),
                    'url': info['url'],
                    'web_url': info['webpage_url'],
                    'thumbnail': info.get('thumbnail'),
                    'duration': info.get('duration'),
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
                        yt_info = await loop.run_in_executor(None, lambda: self._search_youtube(song_name))
                        if yt_info:
                            songs.append({
                                'name': song_name,
                                'url': yt_info['url'],
                                'web_url': yt_info['web_url'],
                                'thumbnail': yt_info['thumbnail'],
                                'duration': yt_info['duration'],
                            })
                        message = f"Added '{song_name}' to the queue."
                    except Exception as e:
                        print(f"Error processing spotify track url: {e}") # Log error
                        return None, f"Could not get Spotify track information: {e}"
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
                yt_info = await loop.run_in_executor(None, lambda: self._search_youtube(song_name))
                if yt_info:
                    songs.append({
                        'name': song_name,
                        'url': yt_info['url'],
                        'web_url': yt_info['web_url'],
                        'thumbnail': yt_info['thumbnail'],
                        'duration': yt_info['duration'],
                    })
                    message = f"Added '{song_name}' to the queue."
            except Exception as e:
                print(f"Error searching spotify: {e}")
                return None, "An error occurred while searching Spotify."
        
        if not songs:
            return None, "Could not find a playable song for your query."

        return songs, message

    def _create_now_playing_embed_and_view(self, song, vc):
        embed = discord.Embed(
            title="Now Playing",
            description=f"[{song['name']}]({song['web_url']})" if song.get('web_url') else song['name'],
            color=discord.Color.blue()
        )
        if song.get('thumbnail'):
            embed.set_thumbnail(url=song['thumbnail'])
        
        if song.get('duration'):
            duration = song['duration']
            minutes, seconds = divmod(duration, 60)
            embed.add_field(name="Duration", value=f"{minutes:02d}:{seconds:02d}", inline=True)

        if song.get('requester'):
            embed.set_footer(text=f"Requested by {song['requester'].display_name}", icon_url=song['requester'].avatar.url)

        view = MusicControlView()
        # Set button state correctly
        if vc and vc.is_paused():
            button = discord.utils.get(view.children, custom_id='pause_resume')
            button.label = "Resume"
            button.emoji = "▶️"
        
        return embed, view

    # Function to play the next song in the queue
    async def play_next(self, ctx):
        guild_id = ctx.guild.id
        if not self.music_queue.get(guild_id):
            self.is_playing[guild_id] = False
            self.current_song[guild_id] = None
            now_playing_msg = self.now_playing_message.get(guild_id)
            if now_playing_msg:
                try:
                    await now_playing_msg.edit(content="Queue finished.", embed=None, view=None)
                except discord.NotFound:
                    pass # Message already gone
                self.now_playing_message[guild_id] = None

            if ctx.voice_client and ctx.voice_client.is_connected():
                await asyncio.sleep(60) # Wait a bit before disconnecting
                if not self.is_playing.get(guild_id) and not self.music_queue.get(guild_id):
                    await ctx.voice_client.disconnect()
            return

        song = self.music_queue[guild_id].pop(0)
        self.current_song[guild_id] = song # Set the current playing song

        embed, view = self._create_now_playing_embed_and_view(song, ctx.voice_client)

        now_playing_msg = self.now_playing_message.get(guild_id)
        if now_playing_msg:
            try:
                await now_playing_msg.edit(content=None, embed=embed, view=view)
            except discord.NotFound:
                 self.now_playing_message[guild_id] = await ctx.channel.send(content=None, embed=embed, view=view)
        else:
            self.now_playing_message[guild_id] = await ctx.channel.send(content=None, embed=embed, view=view)


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

    @commands.command(name='player', help='Brings the music player to the bottom of the chat.')
    async def player(self, ctx):
        guild_id = ctx.guild.id
        
        current_song = self.current_song.get(guild_id)
        if not current_song or not ctx.voice_client:
            await ctx.send("Nothing is currently playing.")
            return
            
        old_message = self.now_playing_message.get(guild_id)
        if old_message:
            try:
                await old_message.delete()
            except (discord.Forbidden, discord.NotFound):
                pass
        
        embed, view = self._create_now_playing_embed_and_view(current_song, ctx.voice_client)
        self.now_playing_message[guild_id] = await ctx.send(embed=embed, view=view)

    async def handle_playlist(self, ctx, query):
        guild_id = ctx.guild.id
        loop = asyncio.get_event_loop()
        
        try:
            playlist_id = query.split('/')[-1].split('?')[0]
            results = self.sp.playlist_tracks(playlist_id)
            
            if not results['items']:
                 await ctx.send("Playlist is empty or could not be accessed.")
                 return
            
            processed_count = 0
            
            def get_all_tracks(results):
                r = results
                while r:
                    for item in r['items']:
                        yield item
                    r = self.sp.next(r) if r['next'] else None
            
            for item in get_all_tracks(results):
                track = item.get('track')
                if not track:
                    continue

                song_name = f"{track['artists'][0]['name']} - {track['name']}"
                
                yt_info = await loop.run_in_executor(None, lambda: self._search_youtube(song_name))
                
                if yt_info:
                    song = {
                        'name': song_name,
                        'url': yt_info['url'],
                        'web_url': yt_info['web_url'],
                        'thumbnail': yt_info['thumbnail'],
                        'duration': yt_info['duration'],
                        'guild_id': guild_id,
                        'channel_id': ctx.channel.id,
                        'requester': ctx.author
                    }
                    self.music_queue[guild_id].append(song)
                    processed_count += 1
                    
                    if not self.is_playing.get(guild_id):
                        self.is_playing[guild_id] = True
                        await self.play_next(ctx)
            
            await ctx.send(f"Finished adding {processed_count} songs to the queue.")

        except Exception as e:
            print(f"Error processing spotify playlist url: {e}")
            await ctx.send(f"Could not get Spotify playlist information: {e}")

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

        if validators.url(query) and 'spotify.com' in query and 'playlist' in query:
            await ctx.send("Processing playlist... this might take a moment.")
            self.bot.loop.create_task(self.handle_playlist(ctx, query))
            return

        await ctx.send("Searching...")
        
        songs, message = await self._get_song_info(query)

        if not songs:
            await ctx.send(message)
            return

        for song in songs:
            song['guild_id'] = guild_id
            song['channel_id'] = ctx.channel.id
            song['requester'] = ctx.author
            self.music_queue[guild_id].append(song)
        
        await ctx.send(message)

        if not self.is_playing.get(guild_id):
            self.is_playing[guild_id] = True
            await self.play_next(ctx)

    @commands.command(name='skip', help='Skips the current song')
    async def skip(self, ctx):
        vc = ctx.voice_client
        if not vc or not (vc.is_playing() or vc.is_paused()):
            await ctx.send("No music is currently playing to skip.")
            return
        
        vc.stop()
        await ctx.send("Skipped the current song.")

    @commands.command(name='stop', help='Stops playback and clears the queue')
    async def stop(self, ctx):
        guild_id = ctx.guild.id
        vc = ctx.voice_client
        if not vc:
            await ctx.send("I am not in a voice channel.")
            return

        if guild_id in self.music_queue:
            self.music_queue[guild_id].clear()
        
        self.is_playing[guild_id] = False
        self.current_song[guild_id] = None

        if vc.is_playing() or vc.is_paused():
            vc.stop()
        
        message = self.now_playing_message.get(guild_id)
        if message:
            try:
                await message.edit(content="Playback stopped.", view=None)
            except discord.NotFound:
                pass
            self.now_playing_message[guild_id] = None

        await ctx.send("Stopped playback and cleared the queue.")

    @commands.command(name='queue', help='Displays the current song queue')
    async def queue(self, ctx):
        guild_id = ctx.guild.id
        
        if not self.music_queue.get(guild_id) and not self.is_playing.get(guild_id):
            await ctx.send("The queue is currently empty.")
            return

        queue_list = []
        if self.is_playing.get(guild_id) and self.current_song.get(guild_id):
            queue_list.append(f"Now Playing: {self.current_song[guild_id]['name']}")
        
        for i, song in enumerate(self.music_queue.get(guild_id, [])):
            queue_list.append(f"{i+1}. {song['name']}")
        
        if queue_list:
            await ctx.send("```\n" + "\n".join(queue_list) + "\n```")
        else:
            await ctx.send("The queue is empty.")

    @commands.command(name='pause', help='Pauses the current song')
    async def pause(self, ctx):
        vc = ctx.voice_client
        if vc and vc.is_playing():
            vc.pause()
            await ctx.send("Playback paused.")
            
            message = self.now_playing_message.get(ctx.guild.id)
            if message and message.view:
                view = message.view
                button = discord.utils.get(view.children, custom_id='pause_resume')
                if button:
                    button.label = "Resume"
                    button.emoji = "▶️"
                    await message.edit(view=view)
        else:
            await ctx.send("No music is currently playing.")
            
    @commands.command(name='resume', help='Resumes the paused song')
    async def resume(self, ctx):
        vc = ctx.voice_client
        if vc and vc.is_paused():
            vc.resume()
            await ctx.send("Playback resumed.")

            message = self.now_playing_message.get(ctx.guild.id)
            if message and message.view:
                view = message.view
                button = discord.utils.get(view.children, custom_id='pause_resume')
                if button:
                    button.label = "Pause"
                    button.emoji = "⏸️"
                    await message.edit(view=view)
        else:
            await ctx.send("No music is currently paused.")

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
    music_cog = Music(bot)
    await bot.add_cog(music_cog)
    bot.add_view(MusicControlView())
