import os
import re
import shutil
import logging
import subprocess
import json
import time
from config import (
    VIDEO_EXTENSIONS, EDITION_KEYWORDS, VERSION_KEYWORDS,
    EXTRAS_KEYWORDS_TO_DIR, BUNDLE_STABILITY_TIMEOUT, BUNDLE_STABILITY_CHECK_INTERVAL
)

def is_video_file(filename):
    """
    Checks if a file has a common video extension.

    Args:
        filename (str): The name of the file to check.

    Returns:
        bool: True if the file is a video, False otherwise.
    """
    return os.path.splitext(filename)[1].lower() in VIDEO_EXTENSIONS

def parse_filename(filename):
    """
    Parses a filename or directory name to extract media information.

    Args:
        filename (str): The filename or directory name to parse.

    Returns:
        dict: A dictionary containing title, year, season, and episode info.
    """
    base_name = os.path.splitext(filename)[0]
    clean_name = re.sub(r'[\._]', ' ', base_name)
    year_match = re.search(r'\b(19[89]\d|20\d{2})\b', clean_name)
    year = int(year_match.group(0)) if year_match else None
    year_pos = year_match.start() if year_match else float('inf')

    se_match = re.search(r'[._ -]?[Ss](\d{1,2})[._ -]?[Ee](\d{1,2})(?:[._ -]?[Ee](\d{1,2}))?', clean_name, re.IGNORECASE)
    season, start_episode, end_episode = None, None, None
    if se_match:
        season = int(se_match.group(1))
        start_episode = int(se_match.group(2))
        end_episode = int(se_match.group(3)) if se_match.group(3) else None
    se_pos = se_match.start() if se_match else float('inf')

    if not se_match:
        s_only_match = re.search(r'[._ -]?[Ss](\d{1,2})\b', clean_name, re.IGNORECASE)
        if s_only_match:
            season = int(s_only_match.group(1))
            se_pos = s_only_match.start()

    end_of_title_pos = min(year_pos, se_pos)
    if end_of_title_pos == float('inf'): end_of_title_pos = None

    title_part = clean_name[:end_of_title_pos].strip()
    title = re.sub(r'\s+', ' ', title_part).strip()
    return {"title": title, "year": year, "season": season, "start_episode": start_episode, "end_episode": end_episode}

def get_edition_info(filename):
    """
    Parses a filename to find edition information by checking against a keyword dictionary.

    Args:
        filename (str): The filename to parse.

    Returns:
        str or None: The formatted edition string (e.g., "{edition-Superfan Cut}") or None.
    """
    fn_lower = filename.lower().replace('.', ' ').replace('_', ' ')
    for keyword, edition_tag in EDITION_KEYWORDS.items():
        if keyword in fn_lower:
            return edition_tag
    return None

def get_version_string(filepath):
    """
    Creates a descriptive string for a file's version based on quality tags.

    Args:
        filepath (str): The full path to the video file.

    Returns:
        str: A descriptive string like "1080p - BluRay" or an empty string.
    """
    filename_lower = os.path.basename(filepath).lower()
    tags = []

    for keyword, tag in VERSION_KEYWORDS['resolution'].items():
        if keyword in filename_lower:
            tags.append(tag)
            break
    for keyword, tag in VERSION_KEYWORDS['source'].items():
        if keyword in filename_lower:
            tags.append(tag)
            break
    return " - ".join(tags)

def get_extra_type(filename):
    """
    Determines if a file is an extra and returns its proper directory name for Plex.

    Args:
        filename (str): The filename to check.

    Returns:
        str or None: The name of the Plex extra directory or None.
    """
    fn_lower = os.path.basename(filename).lower().replace(" ", "").replace("-", "").replace("_", "")
    for keyword, dir_name in EXTRAS_KEYWORDS_TO_DIR.items():
        if keyword in fn_lower:
            return dir_name
    return None

def get_quality_score(filepath):
    """
    Calculates a numeric quality score for a video file to decide on upgrades.

    Args:
        filepath (str): The full path to the video file.

    Returns:
        int: A numeric score representing the video's quality.
    """
    if not os.path.exists(filepath): return 0
    filename_lower = os.path.basename(filepath).lower()
    score = 0

    # This logic is intentionally duplicated from get_version_string to allow
    # independent scoring if needed in the future.
    if '2160p' in filename_lower or '4k' in filename_lower: score = 400
    elif '1080p' in filename_lower: score = 300
    elif '720p' in filename_lower: score = 200
    elif '480p' in filename_lower or 'sd' in filename_lower: score = 100

    if score == 0:
        command = ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_streams", filepath]
        try:
            result = subprocess.run(command, capture_output=True, text=True, check=True)
            data = json.loads(result.stdout)
            video_stream = next((s for s in data.get('streams', []) if s.get('codec_type') == 'video'), None)
            resolution = int(video_stream['height']) if video_stream and 'height' in video_stream else 0
            if resolution >= 2160: score = 400
            elif resolution >= 1080: score = 300
            elif resolution >= 720: score = 200
            elif resolution > 0: score = 100
        except Exception as e:
            logging.error(f"ffprobe failed for '{os.path.basename(filepath)}': {e}. Quality score may be inaccurate.")

    if 'remux' in filename_lower: score += 50
    elif 'bluray' in filename_lower: score += 45
    elif 'web-dl' in filename_lower or 'webrip' in filename_lower: score += 40
    elif 'hdtv' in filename_lower: score += 20
    return score

def safe_remove(path, is_source_bundle=False, DELETE_SOURCE_FILES=False):
    """
    Safely removes a file or an entire directory, respecting the DELETE_SOURCE_FILES setting.

    Args:
        path (str): The path to the file or directory to remove.
        is_source_bundle (bool): If True, respects the DELETE_SOURCE_FILES setting.
        DELETE_SOURCE_FILES (bool): The global setting for deletion.
    """
    if is_source_bundle and not DELETE_SOURCE_FILES: return
    try:
        if not path or not os.path.exists(path): return
        if os.path.isdir(path):
            shutil.rmtree(path)
            logging.info(f"Cleaned up source bundle: {path}")
        elif os.path.isfile(path):
            os.remove(path)
            logging.info(f"Cleaned up source file: {os.path.basename(path)}")
    except OSError as e:
        logging.error(f"Failed to remove path '{path}': {e}")

def get_snapshot(path):
    """
    Creates a snapshot of a file or a directory's contents (files and sizes).

    Args:
        path (str): The file or directory path to snapshot.

    Returns:
        dict: A dictionary of {filepath: size}.
    """
    snapshot = {}
    if not os.path.exists(path): return snapshot

    if os.path.isdir(path):
        for root, _, files in os.walk(path):
            for name in files:
                try:
                    filepath = os.path.join(root, name)
                    snapshot[filepath] = os.path.getsize(filepath)
                except FileNotFoundError:
                    continue
    elif os.path.isfile(path):
        try:
            snapshot[path] = os.path.getsize(path)
        except FileNotFoundError:
            pass

    return snapshot

def wait_for_stability(path):
    """
    Actively polls a file or directory to ensure it is static before processing.

    Args:
        path (str): The file or directory path to check.

    Returns:
        bool: True if stable, False if it times out.
    """
    item_name = os.path.basename(path)
    logging.info(f"Actively checking '{item_name}' for stability...")
    last_snapshot = {}
    start_time = time.time()

    while time.time() - start_time < BUNDLE_STABILITY_TIMEOUT:
        current_snapshot = get_snapshot(path)

        if current_snapshot and current_snapshot == last_snapshot:
            logging.info(f"'{item_name}' is stable.")
            return True

        last_snapshot = current_snapshot
        logging.info(f"'{item_name}' is still active. Found {len(current_snapshot)} files. Waiting {BUNDLE_STABILITY_CHECK_INTERVAL}s...")
        time.sleep(BUNDLE_STABILITY_CHECK_INTERVAL)

    logging.error(f"Stability check for '{item_name}' timed out after {BUNDLE_STABILITY_TIMEOUT} seconds.")
    return False

def get_existing_version_info(dest_dir, base_filename):
    """
    Scans a destination directory to find the highest quality score for each existing edition.

    Args:
        dest_dir (str): The destination directory to scan.
        base_filename (str): The base name of the media to look for.

    Returns:
        dict: A dictionary mapping edition tags to their highest quality score.
    """
    versions = {}
    if not os.path.isdir(dest_dir):
        return versions

    for filename in os.listdir(dest_dir):
        if filename.startswith(base_filename) and is_video_file(filename):
            edition = get_edition_info(filename) or "{edition-Theatrical Cut}"
            score = get_quality_score(os.path.join(dest_dir, filename))

            if edition not in versions or score > versions[edition]:
                versions[edition] = score
    return versions
