# Description
Discord bot to play music in VC. Uses Spotify API to load songs, ffmpeg to stream audio.

# Get started
1. Create a `.env` file.
2. Go to Discord's developer portal and create a new app. Copy its token into `.env`:
   `DISCORD_TOKEN=`
3. Go to Spotify's Developer Dashboard and create a new app. Copy `client_id` and `client_secret` into `.env`:
   `SPOTIPY_CLIENT_ID=`
   `SPOTIPY_CLIENT_SECRET=`
4. Install Python dependencies:
   `pip install -r requirements.txt`
5. Run the bot locally:
   `python bot.py`
6. Invite the bot to your server and grant the required permissions.
7. Use `!help` to list available commands.

# Docker Deployment

## Local Docker run

1. Build the image:
   `docker build -t spotibot:latest .`
2. Run the container with environment variables:
   `docker run --env-file .env --restart unless-stopped spotibot:latest`

## Local Docker Compose

1. Ensure `.env` contains the required variables.
2. Start the service:
   `docker compose up --build -d`

# GitHub Actions

This repository includes a workflow at `.github/workflows/docker-deploy.yml`.

- On push to `main`, GitHub Actions builds the Docker image.
- The workflow publishes the image to GitHub Container Registry as:
  `ghcr.io/<owner>/spotibot:latest`
  and `ghcr.io/<owner>/spotibot:<commit-sha>`.

## Required steps for GitHub Actions

1. Ensure your repository branch is `main` or update the workflow branch filter.
2. No additional secret is required for GHCR if using `GITHUB_TOKEN`.
3. After push, the image is available from GHCR for deployment.

# Notes

- The bot now loads `cogs.music` before startup so Docker will fail fast if the extension has issues.
- `ffmpeg` is installed in the Docker image so audio streaming works in the container.
- The existing `run_forever.sh` loop is no longer required for Docker deployment.

# Important

You may provide a Spotify public playlist link, a YouTube link, or a simple text search query for the `!play` command. If the playlist is private, the bot will not be able to load it.
