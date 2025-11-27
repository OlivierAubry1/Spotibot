#!/bin/bash

# Print a welcome message
echo "Starting Spotibot Loop..."
echo "Press [CTRL+C] to stop everything."

# Start an infinite loop
while true
do
    # Log the restart time so you know when it happened
    echo "---------------------------------"
    echo "Starting bot at $(date)"
    echo "---------------------------------"
    
    # Run the bot using the Python inside your virtual environment
    # Note: If your venv folder is named differently, update './venv'
    ./venv/bin/python3 bot.py
    
    # The script waits here until bot.py finishes (crashes or is stopped)
    
    # Once bot.py stops, print a message and wait
    echo "Bot stopped. Restarting in 5 seconds..."
    sleep 5
done
