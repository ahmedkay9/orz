import os
import re
import shutil
import time
import logging
import subprocess
import json
import queue
import threading
from dotenv import load_dotenv
from colorama import init, Fore, Style
from thefuzz import process as fuzzy_process
from watchdog.observers.polling import PollingObserver as Observer
from watchdog.events import FileSystemEventHandler

# --- CONFIGURATION ---
# Load environment variables from a .env file for easy configuration.
load_dotenv()
API_KEY = os.getenv('TVDB_API_KEY')
SOURCE_DIR = os.getenv('SOURCE_DIR', '/watch')
DEST_BASE_DIR = os.getenv('DEST_BASE_DIR', '/data')
TV_DIR = os.getenv('TV_DIR', os.path.join(DEST_BASE_DIR, 'tv'))
MOVIES_DIR = os.getenv('MOVIES_DIR', os.path.join(DEST_BASE_DIR, 'movies'))
CONFIDENCE_THRESHOLD = int(os.getenv('CONFIDENCE_THRESHOLD', '85'))
DELETE_SOURCE_FILES = os.getenv('DELETE_SOURCE_FILES', 'false').lower() in ('true', '1', 't')
# Time to wait after the last file event before starting the stability check.
PROCESS_DELAY = int(os.getenv('PROCESS_DELAY', '5'))
# --- Active Stability Check Configuration ---
# How often to check for changes during the active stability check.
BUNDLE_STABILITY_CHECK_INTERVAL = int(os.getenv('BUNDLE_STABILITY_CHECK_INTERVAL', '2'))
# Maximum time to wait for a bundle to become stable before giving up.
BUNDLE_STABILITY_TIMEOUT = int(os.getenv('BUNDLE_STABILITY_TIMEOUT', '300')) # 5 minutes


# --- PLEX NAMING CONSTANTS ---
SUBTITLE_EXTENSIONS = {".srt", ".vtt", ".ass", ".ssa", ".sub"}
VIDEO_EXTENSIONS = {".mp4", ".mkv", ".avi", ".mov", ".flv", ".wmv"}
EXTRAS_KEYWORDS_TO_DIR = {
    "featurette": "Featurettes", "behindthescenes": "Behind The Scenes",
    "deleted": "Deleted Scenes", "interview": "Interviews", "scene": "Scenes",
    "short": "Shorts", "trailer": "Trailers", "gag": "Featurettes",
    "bloopers": "Featurettes", "vfx": "Featurettes"
}
# A map to normalize language names to two-letter codes for subtitles.
LANG_CODE_MAP = {
    'english': 'en', 'eng': 'en',
    'spanish': 'es', 'spa': 'es', 'esp': 'es',
    'french': 'fr', 'fre': 'fr',
    'german': 'de', 'ger': 'de',
    'italian': 'it', 'ita': 'it'
} # Add more as needed

# --- INITIALIZATION ---
# Initialize colorama for cross-platform colored terminal text.
init(autoreset=True)

# --- CUSTOM LOGGING FORMATTER FOR COLORED OUTPUT ---
class ColoredFormatter(logging.Formatter):
    """
    A custom logging formatter to add colors to log messages based on their severity level.
    This makes console output easier to read and scan for issues.
    """
    LOG_COLORS = {
        logging.DEBUG: Style.DIM + Fore.WHITE,
        logging.INFO: Fore.WHITE,
        logging.WARNING: Fore.YELLOW,
        logging.ERROR: Fore.RED,
        logging.CRITICAL: Fore.RED + Style.BRIGHT,
    }

    def format(self, record):
        """
        Overrides the default format method to apply color to the log message.

        Args:
            record (logging.LogRecord): The log record to format.

        Returns:
            str: The formatted and colored log message.
        """
        color = self.LOG_COLORS.get(record.levelno)
        message = super().format(record)
        return f"{color}{message}{Style.RESET_ALL}" if color else message

# --- TVDB API SINGLETON ---
# Use a singleton pattern to ensure we only initialize the TVDB API client once.
TVDB_API = None
def get_tvdb_instance():
    """
    Initializes and returns a single, shared instance of the TVDB API client.
    This prevents re-authenticating for every API call.

    Returns:
        tvdb_v4_official.TVDB: The initialized TVDB API client instance.
    """
    global TVDB_API
    if TVDB_API is None:
        import tvdb_v4_official
        TVDB_API = tvdb_v4_official.TVDB(API_KEY)
    return TVDB_API

# --- HELPER FUNCTIONS ---
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
    It robustly handles various naming conventions for movies and TV shows.

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

def get_extra_type(filename):
    """
    Determines if a file is an extra (e.g., trailer, deleted scene) and returns
    its proper directory name for Plex.

    Args:
        filename (str): The filename to check.

    Returns:
        str or None: The name of the Plex extra directory (e.g., "Trailers") or None.
    """
    fn_lower = os.path.basename(filename).lower().replace(" ", "").replace("-", "").replace("_", "")
    for keyword, dir_name in EXTRAS_KEYWORDS_TO_DIR.items():
        if keyword in fn_lower:
            return dir_name
    return None

def get_quality_score(filepath):
    """
    Calculates a numeric quality score for a video file to decide on upgrades.
    It checks filename tags first, then falls back to ffprobe for resolution.

    Args:
        filepath (str): The full path to the video file.

    Returns:
        int: A numeric score representing the video's quality.
    """
    if not os.path.exists(filepath): return 0
    filename_lower = os.path.basename(filepath).lower()
    score = 0
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

def search_tvdb_metadata(parsed_info, media_type=None):
    """
    Searches TheTVDB for metadata, now checking English translations for better matching.

    Args:
        parsed_info (dict): The output from the parse_filename function.
        media_type (str, optional): A hint ('series' or 'movie') to help filter search results.

    Returns:
        dict or None: The verified metadata from TVDB, or None if no confident match is found.
    """
    query = parsed_info["title"]
    if not query: return None
    try:
        tvdb = get_tvdb_instance()
        search_results = tvdb.search(query=query, year=parsed_info.get("year"), limit=10)

        if not search_results:
            logging.warning(f"No TVDB results found for query: '{query}'")
            return None

        if media_type:
            search_results = [r for r in search_results if r.get('type') == media_type]
        if not search_results:
            logging.warning(f"Found results for '{query}', but none matched required type '{media_type}'.")
            return None

        choices = {}
        for result in search_results:
            if result.get('name'):
                choices[result['name']] = result
            if (result.get('translations', {}).get('eng') and
                    result['translations']['eng'] != result.get('name')):
                choices[result['translations']['eng']] = result

        if not choices:
            logging.warning(f"No usable names found in search results for '{query}'.")
            return None

        best_match_name, confidence = fuzzy_process.extractOne(query, choices.keys())

        if confidence >= CONFIDENCE_THRESHOLD:
            selected_result = choices[best_match_name]
            if selected_result.get('translations', {}).get('eng'):
                selected_result['name'] = selected_result['translations']['eng']

            logging.info(f"Confident match for '{query}': '{selected_result['name']}' (Matched on: '{best_match_name}', Confidence: {confidence}%).")
            return selected_result
        else:
            logging.warning(f"Low confidence for '{query}': Best guess '{best_match_name}' ({confidence}%) is below threshold.")
            return None
    except Exception as e:
        logging.error(f"Error during TVDB search: {e}", exc_info=True)
        return None

def safe_remove(path, is_source_bundle=False):
    """
    Safely removes a file or an entire directory, respecting the DELETE_SOURCE_FILES setting.

    Args:
        path (str): The path to the file or directory to remove.
        is_source_bundle (bool): If True, respects the DELETE_SOURCE_FILES setting.
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

# --- BUNDLE STABILITY CHECKER ---
def get_snapshot(path):
    """
    Creates a snapshot of a file or a directory's contents (files and sizes).

    Args:
        path (str): The file or directory path to snapshot.

    Returns:
        dict: A dictionary of {filepath: size}. Returns a single item for a file.
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
            pass # File was deleted during check.

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

        if current_snapshot == last_snapshot:
            logging.info(f"'{item_name}' is stable.")
            return True

        last_snapshot = current_snapshot
        logging.info(f"'{item_name}' is still active. Found {len(current_snapshot)} files. Waiting {BUNDLE_STABILITY_CHECK_INTERVAL}s...")
        time.sleep(BUNDLE_STABILITY_CHECK_INTERVAL)

    logging.error(f"Stability check for '{item_name}' timed out after {BUNDLE_STABILITY_TIMEOUT} seconds.")
    return False

# --- BUNDLE AND FILE PROCESSING LOGIC ---
def process_subtitles(subtitle_files, media_files_map):
    """
    Processes and renames subtitle files to match their corresponding video files.

    Args:
        subtitle_files (list): A list of tuples (full_path, filename) for subtitle files.
        media_files_map (dict): A dictionary mapping original video full_path to its final destination full_path.
    """
    video_basename_map = {os.path.splitext(os.path.basename(v_path))[0]: v_path for v_path in media_files_map.keys()}

    for sub_path, _ in subtitle_files:
        sub_basename = os.path.splitext(os.path.basename(sub_path))[0]
        sub_ext = os.path.splitext(sub_path)[1]

        matching_video_path = None
        for vid_basename, vid_path in video_basename_map.items():
            if sub_basename.startswith(vid_basename):
                matching_video_path = vid_path
                break

        if not matching_video_path:
            logging.warning(f"Could not find a matching video for subtitle '{os.path.basename(sub_path)}'. Skipping.")
            continue

        final_video_path = media_files_map.get(matching_video_path)
        if not final_video_path: continue

        final_video_basename = os.path.splitext(os.path.basename(final_video_path))[0]
        final_video_dir = os.path.dirname(final_video_path)

        lang_tag = "en"
        forced_tag = ""
        potential_tags_str = sub_basename[len(os.path.splitext(os.path.basename(matching_video_path))[0]):]
        parts = potential_tags_str.lower().split('.')

        for tag in reversed(parts):
            if not tag: continue
            if tag in ['forced', 'sdh']:
                forced_tag = f".{tag}"
            elif tag in LANG_CODE_MAP:
                lang_tag = LANG_CODE_MAP[tag]
            elif len(tag) in [2, 3] and tag.isalpha():
                lang_tag = tag

        final_sub_filename = f"{final_video_basename}.{lang_tag}{forced_tag}{sub_ext}"
        final_sub_path = os.path.join(final_video_dir, final_sub_filename)

        if not os.path.exists(final_sub_path):
            logging.info(f"Copying subtitle to: {os.path.basename(final_sub_path)}")
            shutil.copy2(sub_path, final_sub_path)

def process_movie_bundle(bundle_path, metadata, video_files, extra_files, subtitle_files):
    # Docstring here...
    logging.info(Fore.CYAN + f"--- Processing as MOVIE Bundle: {os.path.basename(bundle_path)} ---")

    main_file = max(video_files, key=lambda f: os.path.getsize(f[0]))[0] if video_files else None
    if not main_file:
        logging.error("No video file found to be the main movie. Skipping bundle.")
        return

    title, year, tvdb_id = metadata["name"], metadata["year"], metadata["tvdb_id"]
    safe_title = re.sub(r'[<>:"/\\|?*]', '', title)
    item_dest_dir = os.path.join(MOVIES_DIR, f"{safe_title} ({year}) {{tvdb-{tvdb_id}}}")
    os.makedirs(item_dest_dir, exist_ok=True)

    main_ext = os.path.splitext(main_file)[1]
    final_main_path = os.path.join(item_dest_dir, f"{safe_title} ({year}){main_ext}")
    final_media_paths = {main_file: final_main_path}

    if os.path.exists(final_main_path):
        new_score, old_score = get_quality_score(main_file), get_quality_score(final_main_path)
        if new_score > old_score:
            logging.info(f"Upgrading movie '{safe_title}' (Score: {old_score} -> {new_score})")
            safe_remove(final_main_path)
            shutil.copy2(main_file, final_main_path)
    else:
        logging.info(f"Copying main movie: {os.path.basename(final_main_path)}")
        shutil.copy2(main_file, final_main_path)

    for extra_path, _ in extra_files:
        extra_type_dir = get_extra_type(os.path.basename(extra_path))
        if extra_type_dir:
            dest_dir = os.path.join(item_dest_dir, extra_type_dir)
            os.makedirs(dest_dir, exist_ok=True)
            base_extra_name = os.path.splitext(os.path.basename(extra_path))[0]
            extra_ext = os.path.splitext(extra_path)[1]
            new_extra_filename = f"{safe_title} ({year}) - {base_extra_name}{extra_ext}"
            dest_path = os.path.join(dest_dir, new_extra_filename)
            if not os.path.exists(dest_path):
                shutil.copy2(extra_path, dest_path)
                logging.info(f"Copied extra to: {os.path.basename(dest_path)}")

    process_subtitles(subtitle_files, final_media_paths)


def process_tv_season_bundle(bundle_path, metadata, video_files, subtitle_files):
    # Docstring here...
    logging.info(Fore.CYAN + f"--- Processing as TV Season Bundle: {os.path.basename(bundle_path)} ---")
    title, year, tvdb_id = metadata["name"], metadata["year"], metadata["tvdb_id"]
    safe_title = re.sub(r'[<>:"/\\|?*]', '', title)
    show_dest_dir = os.path.join(TV_DIR, f"{safe_title} ({year}) {{tvdb-{tvdb_id}}}")

    final_media_paths = {}

    for episode_path, _ in video_files:
        parsed_episode = parse_filename(os.path.basename(episode_path))
        season, start_ep = parsed_episode.get("season"), parsed_episode.get("start_episode")
        end_ep = parsed_episode.get("end_episode")

        if season is None or start_ep is None:
            logging.warning(f"Could not parse season/episode from '{os.path.basename(episode_path)}'. Skipping file.")
            continue

        season_dest_dir = os.path.join(show_dest_dir, f"Season {season:02d}")
        os.makedirs(season_dest_dir, exist_ok=True)

        ep_str = f"e{start_ep:02d}"
        if end_ep: ep_str += f"-e{end_ep:02d}"

        ep_ext = os.path.splitext(episode_path)[1]
        final_ep_filename = f"{safe_title} ({year}) - s{season:02d}{ep_str}{ep_ext}"
        final_ep_path = os.path.join(season_dest_dir, final_ep_filename)
        final_media_paths[episode_path] = final_ep_path

        if os.path.exists(final_ep_path):
            new_score, old_score = get_quality_score(episode_path), get_quality_score(final_ep_path)
            if new_score > old_score:
                logging.info(f"Upgrading episode '{os.path.basename(final_ep_path)}' (Score: {old_score} -> {new_score})")
                safe_remove(final_ep_path)
                shutil.copy2(episode_path, final_ep_path)
        else:
            logging.info(f"Copying episode: {os.path.basename(final_ep_path)}")
            shutil.copy2(episode_path, final_ep_path)

    process_subtitles(subtitle_files, final_media_paths)


def process_bundle(bundle_path):
    # Docstring here...
    logging.info(Fore.MAGENTA + f"--- Analyzing Bundle: {os.path.basename(bundle_path)} ---")

    video_files, extra_files, subtitle_files = [], [], []
    for root, _, files in os.walk(bundle_path):
        for filename in files:
            filepath = os.path.join(root, filename)
            if is_video_file(filename):
                file_info = (filepath, filename)
                if get_extra_type(filename):
                    extra_files.append(file_info)
                else:
                    video_files.append(file_info)
            elif os.path.splitext(filename)[1].lower() in SUBTITLE_EXTENSIONS:
                subtitle_files.append((filepath, filename))

    if not video_files:
        logging.error(f"No processable video files found in bundle '{os.path.basename(bundle_path)}'. Skipping.")
        return

    context_info = parse_filename(os.path.basename(bundle_path))

    is_series_hint = any(parse_filename(f[1]).get("season") for f in video_files) or context_info.get("season")
    media_type_hint = "series" if is_series_hint else "movie"
    logging.info(f"Hinting bundle type as '{media_type_hint}' based on filenames.")

    metadata = search_tvdb_metadata(context_info, media_type=media_type_hint)
    if not metadata:
        logging.error(f"Could not find metadata for bundle '{os.path.basename(bundle_path)}'. Skipping.")
        return

    if metadata['type'] == 'series':
        process_tv_season_bundle(bundle_path, metadata, video_files, subtitle_files)
    elif metadata['type'] == 'movie':
        process_movie_bundle(bundle_path, metadata, video_files, extra_files, subtitle_files)
    else:
        logging.warning(f"Unrecognized media type '{metadata['type']}' for bundle. Skipping.")

    safe_remove(bundle_path, is_source_bundle=True)

def process_single_file(filepath):
    """
    Handles the logic for a single media file dropped directly into the watch folder.
    This is separate from the bundle processing logic.
    """
    logging.info(Fore.CYAN + f"--- Processing Single File: {os.path.basename(filepath)} ---")
    parsed_info = parse_filename(os.path.basename(filepath))

    media_type_hint = "series" if parsed_info.get("season") else "movie"
    metadata = search_tvdb_metadata(parsed_info, media_type=media_type_hint)

    if not metadata:
        logging.error(f"Could not find metadata for file '{os.path.basename(filepath)}'. Skipping.")
        return

    # Delegate to the appropriate bundle processor, creating a dummy "bundle"
    if metadata['type'] == 'series':
        process_tv_season_bundle(filepath, metadata, [(filepath, os.path.basename(filepath))], [])
    elif metadata['type'] == 'movie':
        process_movie_bundle(filepath, metadata, [(filepath, os.path.basename(filepath))], [], [])

    safe_remove(filepath, is_source_bundle=True)

# --- DIRECTORY WATCHER AND QUEUE MANAGER ---
class ChangeHandler(FileSystemEventHandler):
    # Docstring here...
    def __init__(self, processing_queue):
        super().__init__()
        self.queue = processing_queue
        self.timers = {}
        self.lock = threading.Lock()

    def on_any_event(self, event):
        # Docstring here...
        if event.is_directory or not os.path.exists(event.src_path): return
        try:
            # For a file directly in SOURCE_DIR, the item itself is the bundle.
            # For a file in a subdirectory, the top-level directory is the bundle.
            relative_path = os.path.relpath(event.src_path, SOURCE_DIR)
            if relative_path.startswith('..'): return

            if os.path.sep in relative_path:
                bundle_name = relative_path.split(os.path.sep)[0]
                item_path = os.path.join(SOURCE_DIR, bundle_name)
            else:
                item_path = event.src_path

            with self.lock:
                if item_path in self.timers: self.timers[item_path].cancel()
                timer = threading.Timer(PROCESS_DELAY, self.queue_item, [item_path])
                self.timers[item_path] = timer
                timer.start()
        except Exception:
            pass

    def queue_item(self, item_path):
        # Docstring here...
        with self.lock:
            if os.path.exists(item_path) and item_path not in list(self.queue.queue):
                logging.info(Fore.CYAN + f"Queueing item for processing: {os.path.basename(item_path)}")
                self.queue.put(item_path)
            self.timers.pop(item_path, None)

def worker(processing_queue):
    """
    The worker thread function that pulls items (files or bundles) from the queue,
    confirms their stability, and then processes them.
    """
    while True:
        item_path = processing_queue.get()
        if item_path is None: break
        try:
            if wait_for_stability(item_path):
                if os.path.isdir(item_path):
                    process_bundle(item_path)
                elif os.path.isfile(item_path):
                    process_single_file(item_path)
            else:
                logging.error(f"Skipping '{os.path.basename(item_path)}' due to stability check timeout.")
        except Exception as e:
            logging.error(f"CRITICAL: Unhandled exception processing '{os.path.basename(item_path)}'.", exc_info=True)
        finally:
            processing_queue.task_done()

def main():
    """Main function to set up logging, the watcher, and the processing queue."""
    log_handler = logging.StreamHandler()
    log_handler.setFormatter(ColoredFormatter('%(asctime)s - %(levelname)s - %(message)s'))
    root_logger = logging.getLogger()
    if root_logger.hasHandlers():
        root_logger.handlers.clear()
    root_logger.addHandler(log_handler)
    root_logger.setLevel(logging.INFO)

    logging.info(f"Starting Orz Media Watcher (v0.36 - Single File & Stability)...")
    logging.info(f"Source Directory: {SOURCE_DIR}")
    if DELETE_SOURCE_FILES: logging.warning("DELETE_SOURCE_FILES is enabled.")

    if not os.path.isdir(SOURCE_DIR): os.makedirs(SOURCE_DIR)
    if not os.path.isdir(DEST_BASE_DIR): os.makedirs(DEST_BASE_DIR)

    processing_queue = queue.Queue()
    worker_thread = threading.Thread(target=worker, args=(processing_queue,))
    worker_thread.daemon = True
    worker_thread.start()

    event_handler = ChangeHandler(processing_queue)
    observer = Observer()
    observer.schedule(event_handler, SOURCE_DIR, recursive=True)
    observer.start()

    try:
        while True: time.sleep(1)
    except KeyboardInterrupt:
        logging.info("Shutting down...")
        observer.stop()
        processing_queue.put(None)

    observer.join()
    worker_thread.join()
    logging.info("Shutdown complete.")

if __name__ == "__main__":
    main()
