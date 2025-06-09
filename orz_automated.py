import os
import re
import shutil
import time
import logging
import subprocess
import json
from dotenv import load_dotenv
from colorama import init, Fore, Style
from thefuzz import process as fuzzy_process
from watchdog.observers.polling import PollingObserver as Observer
from watchdog.events import FileSystemEventHandler

# --- CONFIGURATION ---
load_dotenv()
API_KEY = os.getenv('TVDB_API_KEY')
SOURCE_DIR = os.getenv('SOURCE_DIR', '/watch')
DEST_BASE_DIR = os.getenv('DEST_BASE_DIR', '/data')
TV_DIR = os.getenv('TV_DIR', os.path.join(DEST_BASE_DIR, 'tv'))
MOVIES_DIR = os.getenv('MOVIES_DIR', os.path.join(DEST_BASE_DIR, 'movies'))
CONFIDENCE_THRESHOLD = int(os.getenv('CONFIDENCE_THRESHOLD', '85'))
DELETE_SOURCE_FILES = os.getenv('DELETE_SOURCE_FILES', 'false').lower() in ('true', '1', 't')
FILE_STABILITY_CHECK_INTERVAL = int(os.getenv('FILE_STABILITY_CHECK_INTERVAL', '2'))
FILE_STABILITY_CHECK_TIMEOUT = int(os.getenv('FILE_STABILITY_CHECK_TIMEOUT', '300'))

# --- PLEX NAMING CONSTANTS ---
SUBTITLE_EXTENSIONS = {".srt", ".vtt", ".ass", ".ssa", ".sub"}
EXTRAS_KEYWORDS_TO_DIR = {
    "featurette": "Featurettes", "behindthescenes": "Behind The Scenes", "deleted": "Deleted Scenes",
    "interview": "Interviews", "scene": "Scenes", "short": "Shorts", "trailer": "Trailers",
}
LANG_CODE_MAP = {
    'english': 'en', 'spanish': 'es', 'french': 'fr', 'german': 'de', 'italian': 'it', 'dutch': 'nl',
    'portuguese': 'pt', 'russian': 'ru', 'japanese': 'ja', 'chinese': 'zh', 'korean': 'ko',
    'arabic': 'ar', 'danish': 'da', 'swedish': 'sv', 'norwegian': 'no', 'finnish': 'fi', 'greek': 'el',
    'romanian': 'ro',
}

# --- INITIALIZATION ---
init(autoreset=True)
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s', handlers=[logging.StreamHandler()])

if not API_KEY:
    raise EnvironmentError("TVDB_API_KEY not found in environment variables.")

TVDB_API = None
def get_tvdb_instance():
    global TVDB_API
    if TVDB_API is None:
        import tvdb_v4_official
        TVDB_API = tvdb_v4_official.TVDB(API_KEY)
    return TVDB_API

VIDEO_EXTENSIONS = {".mp4", ".mkv", ".avi", ".mov", ".flv", ".wmv"}

def is_video_file(filename):
    return os.path.splitext(filename)[1].lower() in VIDEO_EXTENSIONS

def wait_for_file_stability(filepath):
    """
    Waits for a file to stop growing in size, indicating the copy is complete.
    """
    logging.info(f"Checking stability for {os.path.basename(filepath)}...")
    last_size = -1
    start_time = time.time()

    while time.time() - start_time < FILE_STABILITY_CHECK_TIMEOUT:
        try:
            if not os.path.exists(filepath):
                logging.warning(f"File {os.path.basename(filepath)} was removed during stability check. Aborting.")
                return False

            current_size = os.path.getsize(filepath)
            if current_size == last_size and current_size > 0:
                logging.info(f"File {os.path.basename(filepath)} is stable at {current_size} bytes.")
                return True

            last_size = current_size
            logging.info(f"File size is {current_size}. Waiting {FILE_STABILITY_CHECK_INTERVAL}s...")
            time.sleep(FILE_STABILITY_CHECK_INTERVAL)

        except FileNotFoundError:
            logging.warning(f"File not found during stability check: {filepath}")
            return False
        except Exception as e:
            logging.error(f"Error during stability check for {filepath}: {e}")
            return False

    logging.error(f"File stability check timed out for {filepath} after {FILE_STABILITY_CHECK_TIMEOUT} seconds.")
    return False

def get_video_resolution(filepath):
    if not os.path.exists(filepath): return 0
    command = ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_streams", filepath]
    try:
        result = subprocess.run(command, capture_output=True, text=True, check=True)
        data = json.loads(result.stdout)
        video_stream = next((s for s in data.get('streams', []) if s.get('codec_type') == 'video'), None)
        return int(video_stream['height']) if video_stream and 'height' in video_stream else 0
    except Exception as e:
        logging.error(f"ffprobe failed for '{os.path.basename(filepath)}': {e}")
        return 0

def get_quality_score(filepath):
    filename_lower = os.path.basename(filepath).lower()
    score = 0
    if '2160p' in filename_lower or '4k' in filename_lower: score = 400
    elif '1080p' in filename_lower: score = 300
    elif '720p' in filename_lower: score = 200
    elif '480p' in filename_lower or 'sd' in filename_lower: score = 100
    if score == 0:
        resolution = get_video_resolution(filepath)
        if resolution >= 2160: score = 400
        elif resolution >= 1080: score = 300
        elif resolution >= 720: score = 200
        elif resolution > 0: score = 100
    if 'bluray' in filename_lower: score += 50
    elif 'remux' in filename_lower: score += 45
    elif 'web-dl' in filename_lower: score += 40
    elif 'webrip' in filename_lower: score += 30
    elif 'hdtv' in filename_lower: score += 20
    return score

def get_extra_type(filename):
    fn_lower = filename.lower().replace(" ", "").replace("-", "").replace("_", "")
    for keyword, dir_name in EXTRAS_KEYWORDS_TO_DIR.items():
        if keyword in fn_lower:
            return dir_name
    return None

def parse_filename(filename):
    base_name = os.path.splitext(filename)[0]
    clean_name = re.sub(r'[\._]', ' ', base_name)
    year_match = re.search(r'\b(19[89]\d|20\d{2})\b', clean_name)
    year = int(year_match.group(0)) if year_match else None
    year_pos = year_match.start() if year_match else float('inf')
    se_match = re.search(r'[Ss](\d{1,2})[._ -]?[Ee](\d{1,2})(?:[._ -]?[Ee](\d{1,2}))?', clean_name, re.IGNORECASE)
    season, start_episode, end_episode = None, None, None
    if se_match:
        season = int(se_match.group(1))
        start_episode = int(se_match.group(2))
        if se_match.group(3):
            end_episode = int(se_match.group(3))
    se_pos = se_match.start() if se_match else float('inf')
    end_of_title_pos = min(year_pos, se_pos)
    title_part = clean_name[:end_of_title_pos].strip()
    title = re.sub(r'\s+', ' ', title_part).strip()
    return {"title": title, "year": year, "season": season, "start_episode": start_episode, "end_episode": end_episode}

def get_destination_path(parsed_info, metadata, ext):
    """Helper function to calculate the final destination path for a file."""
    title, year, tvdb_id, is_series = metadata.get("name"), metadata.get("year"), metadata.get("tvdb_id"), metadata.get("type") == "series"
    safe_title = re.sub(r'[<>:"/\\|?*]', '', title)
    season, start_episode, end_episode = parsed_info.get("season"), parsed_info.get("start_episode"), parsed_info.get("end_episode")

    if is_series and season is not None and start_episode is not None:
        episode_str = f"e{start_episode:02d}"
        if end_episode: episode_str += f"-e{end_episode:02d}"
        base_filename = f"{safe_title} ({year}) - s{season:02d}{episode_str}"
        item_dest_dir = os.path.join(TV_DIR, f"{safe_title} ({year}) {{tvdb-{tvdb_id}}}")
        final_file_dir = os.path.join(item_dest_dir, f"Season {season:02d}")
    else:
        base_filename = f"{safe_title} ({year})"
        item_dest_dir = os.path.join(MOVIES_DIR, f"{base_filename} {{tvdb-{tvdb_id}}}")
        final_file_dir = item_dest_dir

    final_filename = f"{base_filename}{ext}"
    return os.path.join(final_file_dir, final_filename), base_filename, final_file_dir, item_dest_dir

def search_and_verify_metadata(parsed_info):
    query = parsed_info["title"]
    is_tv_show_format = parsed_info.get("season") is not None
    if not query: return None
    try:
        tvdb = get_tvdb_instance()
        search_results = tvdb.search(query=query, year=parsed_info.get("year"), limit=10)

        if not search_results:
            logging.warning(f"No TVDB results found for query: '{query}'")
            return None

        if is_tv_show_format:
            original_count = len(search_results)
            search_results = [r for r in search_results if r.get('type') == 'series']
            logging.info(f"Filename indicates a TV show. Filtering results from {original_count} to {len(search_results)} series matches.")

        if not search_results:
            logging.warning(f"Found results for '{query}', but none were of the required type ('series').")
            return None

        choices = {result['name']: result for result in search_results}
        best_match, confidence = fuzzy_process.extractOne(query, choices.keys())

        if confidence >= CONFIDENCE_THRESHOLD:
            selected_result = choices[best_match]
            if is_tv_show_format and selected_result.get('type') != 'series':
                 logging.error(f"FATAL LOGIC ERROR: Matched '{best_match}' but it is not a series. This should not happen.")
                 return None

            logging.info(f"Confident match for '{query}': '{best_match}' (Type: {selected_result.get('type')}, Confidence: {confidence}%).")
            return selected_result
        else:
            logging.warning(f"Low confidence for '{query}': Best guess '{best_match}' ({confidence}%) is below threshold.")
            return None

    except Exception as e:
        logging.error(f"Error during TVDB search: {e}")
        return None

def safe_remove(path, is_source=False):
    """Safely removes a file or directory, respecting the DELETE_SOURCE_FILES setting."""
    if is_source and not DELETE_SOURCE_FILES:
        return

    try:
        if not path: return
        if os.path.isdir(path):
            shutil.rmtree(path)
            logging.info(f"Removed directory: {path}")
        elif os.path.isfile(path):
            os.remove(path)
            if is_source:
                logging.info(f"Cleaned up source file: {os.path.basename(path)}")
    except OSError as e:
        logging.error(f"Failed to remove path '{path}': {e}")

def process_file(filepath, metadata):
    """Processes a file using pre-fetched metadata."""
    if not os.path.exists(filepath):
        return

    filename = os.path.basename(filepath)
    source_extras = []
    source_folder = os.path.dirname(filepath)
    for f in os.listdir(source_folder):
        if f != filename and os.path.isfile(os.path.join(source_folder, f)):
             source_extras.append(os.path.join(source_folder, f))

    logging.info(Fore.CYAN + f"--- Processing Main File: {filename} ---")

    parsed_info = parse_filename(filename)
    ext = os.path.splitext(filename)[1]
    final_dest_path, base_filename, final_file_dir, item_dest_dir = get_destination_path(parsed_info, metadata, ext)

    os.makedirs(final_file_dir, exist_ok=True)
    if os.path.exists(final_dest_path):
        logging.warning(f"Exact file already exists: {final_dest_path}. Skipping source file.")
        safe_remove(filepath, is_source=True)
        for extra in source_extras: safe_remove(extra, is_source=True)
        return

    existing_file_path = None
    for f in os.listdir(final_file_dir):
        if f.startswith(base_filename):
            existing_file_path = os.path.join(final_file_dir, f)
            break

    if existing_file_path:
        new_score = get_quality_score(filepath)
        existing_score = get_quality_score(existing_file_path)
        if new_score > existing_score:
            logging.info(f"Upgrading '{os.path.basename(existing_file_path)}' (Score: {existing_score}) with new file (Score: {new_score}).")
            safe_remove(existing_file_path)
            shutil.rmtree(os.path.join(item_dest_dir, 'Subtitles'), ignore_errors=True)
            shutil.rmtree(os.path.join(item_dest_dir, 'Featurettes'), ignore_errors=True)
        else:
            logging.warning(f"Skipping, existing file has same/higher quality.")
            safe_remove(filepath, is_source=True)
            for extra in source_extras: safe_remove(extra, is_source=True)
            return

    try:
        shutil.copy2(filepath, final_dest_path)
        logging.info(Fore.GREEN + f"Successfully copied main file to: {final_dest_path}")
        safe_remove(filepath, is_source=True)

        for extra_filepath in source_extras:
            extra_filename = os.path.basename(extra_filepath)
            extra_ext = os.path.splitext(extra_filename)[1].lower()
            if extra_ext in SUBTITLE_EXTENSIONS:
                sub_basename = os.path.splitext(extra_filename)[0]
                lang_match = re.search(r'[._ -]?(\w+)$', sub_basename)
                lang_code = 'en'
                if lang_match:
                    lang_str = lang_match.group(1).lower()
                    if lang_str in LANG_CODE_MAP: lang_code = LANG_CODE_MAP[lang_str]
                    elif len(lang_str) in [2, 3]: lang_code = lang_str
                sub_filename = f"{base_filename}.{lang_code}{extra_ext}"
                dest_path = os.path.join(final_file_dir, sub_filename)
                shutil.copy2(extra_filepath, dest_path)
                logging.info(f"Copied subtitle to: {dest_path}")
            elif is_video_file(extra_filename):
                extra_type_dir_name = get_extra_type(extra_filename)
                if extra_type_dir_name:
                    extra_dest_dir = os.path.join(item_dest_dir, extra_type_dir_name)
                    os.makedirs(extra_dest_dir, exist_ok=True)
                    dest_path = os.path.join(extra_dest_dir, extra_filename)
                    shutil.copy2(extra_filepath, dest_path)
                    logging.info(f"Copied extra '{extra_filename}' to: {dest_path}")
            safe_remove(extra_filepath, is_source=True)

    except Exception as e:
        logging.error(f"Failed during copy of '{filename}': {e}")

class NewFileHandler(FileSystemEventHandler):
    def on_created(self, event):
        if event.is_directory or not os.path.exists(event.src_path):
            return

        filepath = event.src_path
        filename = os.path.basename(filepath)

        if not is_video_file(filename) or get_extra_type(filename) is not None:
            return

        logging.info(f"Watchdog detected new MAIN file: {filename}.")

        if not wait_for_file_stability(filepath):
            return

        parsed_info = parse_filename(filename)
        metadata = search_and_verify_metadata(parsed_info)

        if not metadata:
            logging.error(f"Pre-check failed to find metadata for '{filename}'. Moving to 'failed'.")
            failed_dir = os.path.join(os.path.dirname(filepath), 'failed')
            os.makedirs(failed_dir, exist_ok=True)
            try: shutil.move(filepath, os.path.join(failed_dir, filename))
            except Exception as e: logging.error(f"Could not move file to failed directory: {e}")
            return

        ext = os.path.splitext(filename)[1]
        final_dest_path, _, _, _ = get_destination_path(parsed_info, metadata, ext)
        if os.path.exists(final_dest_path):
            logging.info(f"Pre-check found existing file for '{filename}'. Skipping.")
            safe_remove(filepath, is_source=True)
            return

        process_file(filepath, metadata)

def main():
    logging.info("Starting Orz Media Watcher (v0.10)...")
    logging.info(f"TV Show Destination: {TV_DIR}")
    logging.info(f"Movie Destination: {MOVIES_DIR}")
    if DELETE_SOURCE_FILES:
        logging.warning(Fore.YELLOW + "DELETE_SOURCE_FILES is enabled. Source files will be removed after processing.")
    else:
        logging.info("DELETE_SOURCE_FILES is disabled. Source files will be preserved.")

    if not os.path.isdir(SOURCE_DIR): os.makedirs(SOURCE_DIR)
    if not os.path.isdir(DEST_BASE_DIR): os.makedirs(DEST_BASE_DIR)
    event_handler = NewFileHandler()
    observer = Observer()
    observer.schedule(event_handler, SOURCE_DIR, recursive=True)
    observer.start()
    try:
        while True: time.sleep(10)
    except KeyboardInterrupt:
        observer.stop()
    observer.join()

if __name__ == "__main__":
    main()
