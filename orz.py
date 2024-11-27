import os
import re
import shutil
import argparse
import tvdb_v4_official # type: ignore
from dotenv import load_dotenv # type: ignore

# Load the environment variables
load_dotenv()
api_key = os.getenv('TVDB_API_KEY')

# Initialize TVDB API
tvdb = tvdb_v4_official.TVDB(api_key)

# Supported video file extensions
VIDEO_EXTENSIONS = {".mp4", ".mkv", ".avi", ".mov", ".flv", ".wmv"}

def is_video_file(filename):
    """Check if the file is a video file based on its extension."""
    _, ext = os.path.splitext(filename)
    return ext.lower() in VIDEO_EXTENSIONS

def parse_filename(filename):
    """
    Dynamically extract the title, year, season, and episode from a filename by identifying
    either the year or the season and episode number as a key anchor and discarding junk
    dynamically based on non-alphanumeric patterns.
    """
    base_name = os.path.splitext(filename)[0]

    # Match the year (e.g., 2014)
    year_match = re.search(r'\b(19|20)\d{2}\b', base_name)
    year = int(year_match.group()) if year_match else None
    year_pos = year_match.start() if year_match else None

    # Look for season and episode (e.g., s01e02)
    season_episode_match = re.search(r's(\d{1,2})e(\d{1,2})', base_name, re.IGNORECASE)
    season, episode = (
        (int(season_episode_match.group(1)), int(season_episode_match.group(2)))
        if season_episode_match
        else (None, None)
    )
    season_episode_pos = season_episode_match.start() if season_episode_match else None

    # Determine the earliest anchor position
    positions = []
    if year_pos is not None:
        positions.append(('year', year_pos))
    if season_episode_pos is not None:
        positions.append(('season_episode', season_episode_pos))

    if positions:
        # Use the earliest anchor position to split the title
        anchor_type, anchor_pos = min(positions, key=lambda x: x[1])
        title_part = base_name[:anchor_pos]
    else:
        # No anchor found, use the whole filename
        title_part = base_name

    # Replace non-alphanumeric runs with spaces
    cleaned_title = re.sub(r'[^a-zA-Z0-9]+', ' ', title_part).strip()

    return {
        "title": cleaned_title,
        "year": year,
        "season": season,
        "episode": episode,
    }

def search_tvdb(filename):
    # Parse filename to get title and year
    parsed_filename = parse_filename(filename)
    title = parsed_filename.get("title")
    year = parsed_filename.get("year")
    query = title.strip()

    if year:
        result = tvdb.search(limit=1, query=query, year=year)
    else:
        result = tvdb.search(limit=1, query=query)

    if result:
        info = result[0]
        primary_language = info.get('primary_language')
        print(f"PRIMARY LANGUAGE: {primary_language}")
        tvdb_id = info.get('tvdb_id')
        media_type = info.get('type')

        # If primary language is not English, get English translation
        if primary_language != 'eng':
            info["name"] = info["translations"]["eng"]

        print(f"Metadata found for: {filename}")
        return info
    else:
        print(f"Metadata not found for {filename}")
        return None

def copy_file(src, dest, confirm):
    """Copy file to destination, optionally asking for user confirmation."""
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    if confirm:
        proceed = input(f"Copy {src} to {dest}? (y/n): ").strip().lower() == "y"
        if not proceed:
            return
    shutil.copy2(src, dest)

def process_file(filepath, dest_base, confirm):
    """Process an individual file."""
    if not is_video_file(filepath):
        # print(f"Skipping non-video file: {filepath}")
        return

    # Parse the filename to get season and episode information
    parsed_filename = parse_filename(os.path.basename(filepath))
    season = parsed_filename.get("season")
    episode = parsed_filename.get("episode")
    parsed_title = parsed_filename.get("title")
    parsed_year = parsed_filename.get("year")

    # Search for metadata using the parsed title and year
    metadata = search_tvdb(os.path.basename(filepath))

    if metadata:
        title = metadata.get("name")
        year = metadata.get("year")
        tvdb_id = metadata.get("tvdb_id")
        ext = os.path.splitext(filepath)[1]

        # Determine if the metadata corresponds to a TV series
        # The TVDB API returns a "type" field that can be "series" or "movie"
        is_series = metadata.get("type") == "series"

        if season is not None and episode is not None and is_series:
            # TV show episode
            season_folder = f"Season {season:02d}"
            episode_file = f"{title} ({year}) - s{season:02d}e{episode:02d}{ext}"
            dest = os.path.join(dest_base, "tv", f"{title} ({year}) {{tvdb-{tvdb_id}}}", season_folder, episode_file)
        else:
            # Movie
            movie_file = f"{title} ({year}) {{tvdb-{tvdb_id}}}{ext}"
            dest = os.path.join(dest_base, "movies", movie_file)

        copy_file(filepath, dest, confirm)
    else:
        print(f"Metadata not found for: {filepath}")

def process_directory(directory, dest_base, confirm):
    """Recursively process a directory for video files."""
    for root, _, files in os.walk(directory):
        for file in files:
            process_file(os.path.join(root, file), dest_base, confirm)

def main():
    parser = argparse.ArgumentParser(description="Organize video files using TVDB API.")
    parser.add_argument("paths", nargs="+", help="Files or directories to process.")
    parser.add_argument("--dest", default="/data", help="Base destination directory.")
    parser.add_argument("--no-confirm", action="store_true", help="Do not ask for confirmation before copying.")

    args = parser.parse_args()
    confirm = not args.no_confirm

    for path in args.paths:
        if os.path.isdir(path):
            process_directory(path, args.dest, confirm)
        elif os.path.isfile(path):
            process_file(path, args.dest, confirm)
        else:
            print(f"Invalid path: {path}")

if __name__ == "__main__":
    main()