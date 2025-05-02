#!/bin/bash

# Directory where the repository is cloned
REPO_DIR="/home/kaseyq/github/camera-feeds"

# Directory to look for updates
DOWNLOADS_DIR="$HOME/Downloads"

# Pattern for update files
UPDATE_PATTERN="camera_feeds_updates*.json"

# Ensure the repository directory exists
if [ ! -d "$REPO_DIR" ]; then
    echo "Repository directory $REPO_DIR not found. Exiting."
    exit 1
fi

# Ensure jq is installed (used for JSON parsing)
if ! command -v jq &> /dev/null; then
    echo "jq is required but not installed. Installing jq..."
    sudo apt update
    sudo apt install -y jq
    if [ $? -ne 0 ]; then
        echo "Failed to install jq. Please install it manually and rerun the script."
        exit 1
    fi
fi

# Change to the repository directory
cd "$REPO_DIR" || exit 1

# Find the latest camera_feeds_updates.json file
UPDATE_FILE=$(ls -t "$DOWNLOADS_DIR"/$UPDATE_PATTERN 2>/dev/null | head -n 1)

if [ -z "$UPDATE_FILE" ]; then
    echo "No camera_feeds_updates.json file found in $DOWNLOADS_DIR. Exiting."
    exit 1
fi

echo "Found update file: $UPDATE_FILE"

# Parse the JSON file and extract file updates
echo "Processing updates from $UPDATE_FILE..."
jq -r 'keys[]' "$UPDATE_FILE" | while IFS= read -r filename; do
    echo "Updating $filename..."
    # Extract the file content and write it to the target file
    jq -r ".[\"$filename\"]" "$UPDATE_FILE" > "$filename"
    # Stage the file for Git commit
    git add "$filename"
done

# Commit and push changes
if git status --porcelain | grep -q '^ M'; then
    git commit -m "Apply updates from $UPDATE_FILE"
    git push origin main
    echo "Changes committed and pushed to GitHub."
else
    echo "No changes to commit."
fi

# Clean up the update file
rm -f "$UPDATE_FILE"
echo "Removed $UPDATE_FILE from $DOWNLOADS_DIR."
echo "Update process complete."

