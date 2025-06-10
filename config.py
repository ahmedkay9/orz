import os
from dotenv import load_dotenv

# --- CORE CONFIGURATION ---
# Load environment variables from a .env file for easy configuration.
load_dotenv()
API_KEY = os.getenv('TVDB_API_KEY')
SOURCE_DIR = os.getenv('SOURCE_DIR', '/watch')
DEST_BASE_DIR = os.getenv('DEST_BASE_DIR', '/data')
TV_DIR = os.getenv('TV_DIR', os.path.join(DEST_BASE_DIR, 'tv'))
MOVIES_DIR = os.getenv('MOVIES_DIR', os.path.join(DEST_BASE_DIR, 'movies'))
CONFIDENCE_THRESHOLD = int(os.getenv('CONFIDENCE_THRESHOLD', '85'))
DELETE_SOURCE_FILES = os.getenv('DELETE_SOURCE_FILES', 'false').lower() in ('true', '1', 't')

# --- WATCHER & STABILITY CONFIGURATION ---
# Time to wait after the last file event before starting the stability check.
PROCESS_DELAY = int(os.getenv('PROCESS_DELAY', '5'))
# How often to check for changes during the active stability check.
BUNDLE_STABILITY_CHECK_INTERVAL = int(os.getenv('BUNDLE_STABILITY_CHECK_INTERVAL', '2'))
# Maximum time to wait for a bundle to become stable before giving up.
BUNDLE_STABILITY_TIMEOUT = int(os.getenv('BUNDLE_STABILITY_TIMEOUT', '300')) # 5 minutes

# --- PLEX NAMING & FILETYPE CONSTANTS ---
SUBTITLE_EXTENSIONS = {".srt", ".vtt", ".ass", ".ssa", ".sub"}
VIDEO_EXTENSIONS = {".mp4", ".mkv", ".avi", ".mov", ".flv", ".wmv"}
EXTRAS_KEYWORDS_TO_DIR = {
    "featurette": "Featurettes", "behindthescenes": "Behind The Scenes",
    "deleted": "Deleted Scenes", "interview": "Interviews", "scene": "Scenes",
    "short": "Shorts", "trailer": "Trailers", "gag": "Featurettes",
    "bloopers": "Featurettes", "vfx": "Featurettes"
}
LANG_CODE_MAP = {
    'english': 'en', 'eng': 'en',
    'spanish': 'es', 'spa': 'es', 'esp': 'es',
    'french': 'fr', 'fre': 'fr',
    'german': 'de', 'ger': 'de',
    'italian': 'it', 'ita': 'it'
}

# --- CUSTOMIZABLE KEYWORDS FOR PARSING ---
# Maps keywords found in a filename to the official Plex {edition} tag.
EDITION_KEYWORDS = {
    'extended': '{edition-Extended Cut}',
    'superfan': '{edition-Superfan Cut}',
    "director's cut": "{edition-Director's Cut}",
    "directors cut": "{edition-Director's Cut}",
    'theatrical': '{edition-Theatrical Cut}',
    'uncut': '{edition-Uncut}',
    'unrated': '{edition-Unrated}',
    'remastered': '{edition-Remastered}',
    'imax': '{edition-IMAX}'
}

# Maps keywords to tags for building a version string (e.g., "1080p BluRay").
VERSION_KEYWORDS = {
    'resolution': {
        '2160p': '4K', '4k': '4K',
        '1080p': '1080p',
        '720p': '720p',
        '576p': '576p',
        '480p': '480p',
        'dvd': 'DVD'
    },
    'source': {
        'remux': 'Remux',
        'bluray': 'BluRay',
        'web-dl': 'WEB-DL',
        'webdl': 'WEB-DL',
        'webrip': 'WEBRip',
        'hdtv': 'HDTV',
        'dvdrip': 'DVDRip'
    }
}
