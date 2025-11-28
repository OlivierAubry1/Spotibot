# Description
Discord bot to play music in VC. Uses Spotify API to load songs, ffmpeg to stream audio. 
# Get started
1. Create a .env file
2. Go on discords developer portal and create a new app. copy its token and paste in .env file:
   `DISCORD_TOKEN=`
3. Go on spotify developper portal and create a new app. Copy client_id, client_secret in the .env file
   `DISCORD_TOKEN=`
   `SPOTIPY_CLIENT_ID=`
   `SPOTIPY_CLIENT_SECRET=`
4. run `pip install -r requirements.txt` in your venv
5.  run `python3 bot.py`
6.  invite bot to your server, and give admin access
7. !help to list commands

# Important

You may give a spotify public playlist link, a youtube link or a simple text search query for the !play command. if the playlist is private, the bot will not be able to load it.
