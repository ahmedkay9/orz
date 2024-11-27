import os
import re
import shutil
import argparse
import tvdb_v4_official  # type: ignore
from dotenv import load_dotenv  # type: ignore
from colorama import init, Fore, Style  # type: ignore

# Initialize colorama
init(autoreset=True)

# Load the environment variables
load_dotenv()
api_key = os.getenv('TVDB_API_KEY')

if not api_key:
    raise EnvironmentError("TVDB_API_KEY not found in environment variables.")

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
    """Search for metadata on TVDB based on the parsed filename."""
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
        tvdb_id = info.get('tvdb_id')
        media_type = info.get('type')

        # If primary language is not English, get English translation
        if primary_language != 'eng' and 'translations' in info and 'eng' in info['translations']:
            info["name"] = info["translations"]["eng"]

        print(Fore.GREEN + f"Metadata found for: {filename}" + Style.RESET_ALL)
        return info
    else:
        print(Fore.RED + f"Metadata not found for: {filename}" + Style.RESET_ALL)
        return None

def prepare_copy_action(src, dest):
    """Prepare the copy action without performing it."""
    return (src, dest)

def collect_copy_actions(filepath, dest_base, actions):
    """Collect the copy actions based on the filepath and destination base."""
    if not is_video_file(filepath):
        return

    parsed_filename = parse_filename(os.path.basename(filepath))
    season = parsed_filename.get("season")
    episode = parsed_filename.get("episode")
    parsed_title = parsed_filename.get("title")
    parsed_year = parsed_filename.get("year")

    metadata = search_tvdb(os.path.basename(filepath))

    if metadata:
        title = metadata.get("name")
        year = metadata.get("year")
        tvdb_id = metadata.get("tvdb_id")
        ext = os.path.splitext(filepath)[1]

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

        if os.path.exists(dest):
            print(Fore.YELLOW + f"Skipping existing file: '{dest}'" + Style.RESET_ALL)
            return  # Skip adding this copy action

        actions.append(prepare_copy_action(filepath, dest))
    else:
        print(Fore.RED + f"Metadata not found for: {filepath}" + Style.RESET_ALL)

def display_actions(actions):
    """Display the list of copy actions to the user in a user-friendly format."""
    if not actions:
        print(Fore.YELLOW + "No files to copy." + Style.RESET_ALL)
        return False

    from shutil import get_terminal_size

    # Get terminal size for dynamic formatting
    terminal_width = get_terminal_size((80, 20)).columns
    separator = "-" * terminal_width

    print(Fore.CYAN + "\nThe following actions will be performed:")
    print(Fore.CYAN + separator)

    for idx, (src, dest) in enumerate(actions, 1):
        # Shorten paths if they are too long
        max_path_length = terminal_width - 40  # Adjust based on desired padding
        display_src = (src if len(src) <= max_path_length else src[:max_path_length-3] + '...')
        display_dest = (dest if len(dest) <= max_path_length else dest[:max_path_length-3] + '...')

        print(Fore.GREEN + f"{idx}.")
        print(Fore.YELLOW + f"   Copy from: " + Fore.WHITE + f"'{display_src}'")
        print(Fore.YELLOW + f"   Copy to  : " + Fore.WHITE + f"'{display_dest}'")
        print()  # Blank line for better readability

    print(Fore.CYAN + separator)

    # Prompt for confirmation
    while True:
        choice = input(Fore.CYAN + "\nDo you want to proceed with these changes? (y/n): " + Style.RESET_ALL).strip().lower()
        if choice in {'y', 'yes'}:
            return True
        elif choice in {'n', 'no'}:
            print(Fore.RED + "Operation cancelled by the user." + Style.RESET_ALL)
            return False
        else:
            print(Fore.RED + "Please enter 'y' or 'n'." + Style.RESET_ALL)

def execute_copy_actions(actions):
    """Execute the collected copy actions."""
    for src, dest in actions:
        try:
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            shutil.copy2(src, dest)
            print(Fore.GREEN + f"Copied '{src}' to '{dest}'" + Style.RESET_ALL)
        except Exception as e:
            print(Fore.RED + f"Failed to copy '{src}' to '{dest}': {e}" + Style.RESET_ALL)

def calculate_total_size(actions):
    """Calculate the total size of all source files to be copied."""
    total_size = 0
    for src, _ in actions:
        if os.path.isfile(src):
            total_size += os.path.getsize(src)
    return total_size

def check_disk_space(dest_base, total_size):
    """Check if there's enough space on the destination."""
    usage = shutil.disk_usage(dest_base)
    available = usage.free

    if total_size > available:
        excess_bytes = total_size - available
        excess_gb = excess_bytes / (1024 ** 3)
        print(Fore.RED + f"Error: Not enough disk space on the destination. You are short by {excess_gb:.2f} GB." + Style.RESET_ALL)
        return False
    return True

def main():
    parser = argparse.ArgumentParser(description="Organize video files using TVDB API.")
    parser.add_argument("paths", nargs="+", help="Files or directories to process.")
    parser.add_argument("--dest", default="/data", help="Base destination directory.")
    parser.add_argument("--no-confirm", action="store_true", help="Do not ask for confirmation before copying.")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be done without making any changes.")

    args = parser.parse_args()
    confirm = not args.no_confirm
    dry_run = args.dry_run

    actions = []

    # Collect all copy actions
    for path in args.paths:
        if os.path.isdir(path):
            for root, _, files in os.walk(path):
                for file in files:
                    filepath = os.path.join(root, file)
                    collect_copy_actions(filepath, args.dest, actions)
        elif os.path.isfile(path):
            collect_copy_actions(path, args.dest, actions)
        else:
            print(Fore.RED + f"Invalid path: {path}" + Style.RESET_ALL)

    if not actions:
        print(Fore.YELLOW + "No valid video files found to process." + Style.RESET_ALL)
        return

    # Calculate total size of files to be copied
    total_size = calculate_total_size(actions)
    available_space = shutil.disk_usage(args.dest).free

    if total_size > available_space:
        excess_bytes = total_size - available_space
        excess_gb = excess_bytes / (1024 ** 3)
        print(Fore.RED + f"Error: Not enough disk space on the destination. You are short by {excess_gb:.2f} GB." + Style.RESET_ALL)
        return

    # If confirmation is needed
    if confirm and not dry_run:
        proceed = display_actions(actions)
        if not proceed:
            return

    if dry_run:
        print(Fore.CYAN + "\nDry-run mode enabled. The following actions would be performed:" + Style.RESET_ALL)
        display_actions(actions)

    if not dry_run:
        # Execute copy actions
        execute_copy_actions(actions)

    print(Fore.CYAN + "\nAll operations completed." + Style.RESET_ALL)

if __name__ == "__main__":
    main()