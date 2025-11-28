#!/bin/bash

echo "Starting Spotibot Loop..."
echo "Press [CTRL+C] to stop everything."

while true
do
    echo "---------------------------------"
    echo "Starting bot at $(date)"
    echo "---------------------------------"
    
    ./venv/bin/python3 bot.py

    echo "Bot stopped. Restarting in 5 seconds..."
    sleep 5
done
