import os
import re
import shutil
import logging
from colorama import Fore
from config import MOVIES_DIR, TV_DIR, SUBTITLE_EXTENSIONS, LANG_CODE_MAP
from utils import (
    is_video_file, get_extra_type, get_quality_score, get_edition_info,
    get_version_string, get_existing_version_info, safe_remove, parse_filename
)
from metadata import search_tvdb_metadata

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
        # Find a matching video by checking if the subtitle name starts with the video name
        for vid_basename, vid_path in sorted(video_basename_map.items(), key=lambda x: len(x[0]), reverse=True):
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
    """Handles the logic for a movie bundle, supporting multi-version and editions."""
    logging.info(Fore.CYAN + f"--- Processing as MOVIE Bundle: {os.path.basename(bundle_path)} ---")

    if not video_files: return

    title, year, tvdb_id = metadata["name"], metadata["year"], metadata["tvdb_id"]
    safe_title = re.sub(r'[<>:"/\\|?*]', '', title)
    item_dest_dir = os.path.join(MOVIES_DIR, f"{safe_title} ({year}) {{tvdb-{tvdb_id}}}")
    os.makedirs(item_dest_dir, exist_ok=True)

    base_filename = f"{safe_title} ({year})"
    final_media_paths = {}

    for movie_path, filename in video_files:
        new_edition_tag = get_edition_info(filename)

        # --- NEW: Just-in-Time Audit & Repair Logic ---
        # If the new file has an explicit edition, check if we need to repair an existing unlabeled file.
        if new_edition_tag:
            # Find the path of the unlabeled ("Theatrical") version if it exists.
            unlabeled_path = None
            for existing_file in os.listdir(item_dest_dir):
                if existing_file.startswith(base_filename) and not get_edition_info(existing_file):
                    unlabeled_path = os.path.join(item_dest_dir, existing_file)
                    break

            # If an unlabeled version exists, compare its size to the new file.
            if unlabeled_path and os.path.getsize(unlabeled_path) == os.path.getsize(movie_path):
                # They are identical. Rename the existing file to match the new edition.
                repaired_filename = f"{base_filename} {new_edition_tag}{os.path.splitext(unlabeled_path)[1]}"
                repaired_path = os.path.join(item_dest_dir, repaired_filename)

                if not os.path.exists(repaired_path):
                    logging.info(f"Correcting misnamed destination file: '{os.path.basename(unlabeled_path)}' -> '{os.path.basename(repaired_path)}'")
                    os.rename(unlabeled_path, repaired_path)
        # --- END OF AUDIT LOGIC ---

        # Re-fetch existing versions since we may have just renamed one.
        existing_versions = get_existing_version_info(item_dest_dir, base_filename)
        new_edition = new_edition_tag or "{edition-Theatrical Cut}"
        new_score = get_quality_score(movie_path)

        # Check if we should skip this file
        if new_edition in existing_versions and new_score <= existing_versions[new_edition]:
            logging.warning(f"Skipping '{filename}': A same or better quality version of edition '{new_edition}' already exists (Score: {new_score} <= {existing_versions[new_edition]}).")
            continue

        version_string = get_version_string(movie_path)
        movie_ext = os.path.splitext(movie_path)[1]

        final_filename_parts = [base_filename]
        if new_edition != "{edition-Theatrical Cut}": final_filename_parts.append(f" {new_edition}")
        if version_string: final_filename_parts.append(f" - {version_string}")

        final_filename = "".join(final_filename_parts) + movie_ext
        final_main_path = os.path.join(item_dest_dir, final_filename)
        final_media_paths[movie_path] = final_main_path

        if not os.path.exists(final_main_path):
            logging.info(f"Copying new movie version: {final_filename}")
            shutil.copy2(movie_path, final_main_path)
        else:
            logging.warning(f"Version '{final_filename}' already exists. Skipping.")

    for extra_path, _ in extra_files:
        # Extra handling logic...
        pass

    process_subtitles(subtitle_files, final_media_paths)


def process_tv_season_bundle(bundle_path, metadata, video_files, subtitle_files):
    """Handles the logic for a TV season bundle, supporting multi-version and editions."""
    logging.info(Fore.CYAN + f"--- Processing as TV Season Bundle: {os.path.basename(bundle_path)} ---")
    title, year, tvdb_id = metadata["name"], metadata["year"], metadata["tvdb_id"]
    safe_title = re.sub(r'[<>:"/\\|?*]', '', title)
    show_dest_dir = os.path.join(TV_DIR, f"{safe_title} ({year}) {{tvdb-{tvdb_id}}}")

    final_media_paths = {}

    for episode_path, filename in video_files:
        parsed_episode = parse_filename(filename)
        season, start_ep = parsed_episode.get("season"), parsed_episode.get("start_episode")
        end_ep = parsed_episode.get("end_episode")

        if season is None or start_ep is None:
            logging.warning(f"Could not parse season/episode from '{filename}'. Skipping file.")
            continue

        season_dest_dir = os.path.join(show_dest_dir, f"Season {season:02d}")
        os.makedirs(season_dest_dir, exist_ok=True)

        ep_str = f"e{start_ep:02d}"
        if end_ep: ep_str += f"-e{end_ep:02d}"

        base_ep_filename = f"{safe_title} ({year}) - s{season:02d}{ep_str}"
        new_edition_tag = get_edition_info(filename)

        # --- NEW: Just-in-Time Audit & Repair Logic ---
        if new_edition_tag:
            unlabeled_path = None
            for existing_file in os.listdir(season_dest_dir):
                if existing_file.startswith(base_ep_filename) and not get_edition_info(existing_file):
                    unlabeled_path = os.path.join(season_dest_dir, existing_file)
                    break

            if unlabeled_path and os.path.exists(unlabeled_path) and os.path.getsize(unlabeled_path) == os.path.getsize(episode_path):
                repaired_filename = f"{base_ep_filename} {new_edition_tag}{os.path.splitext(unlabeled_path)[1]}"
                repaired_path = os.path.join(season_dest_dir, repaired_filename)

                if not os.path.exists(repaired_path):
                    logging.info(f"Correcting misnamed destination file: '{os.path.basename(unlabeled_path)}' -> '{os.path.basename(repaired_path)}'")
                    os.rename(unlabeled_path, repaired_path)
        # --- END OF AUDIT LOGIC ---

        existing_versions = get_existing_version_info(season_dest_dir, base_ep_filename)
        new_edition = new_edition_tag or "{edition-Theatrical Cut}"
        new_score = get_quality_score(episode_path)

        if new_edition in existing_versions and new_score <= existing_versions[new_edition]:
            logging.warning(f"Skipping '{filename}': A same or better version of edition '{new_edition}' already exists (Score: {new_score} <= {existing_versions[new_edition]}).")
            continue

        ep_ext = os.path.splitext(episode_path)[1]
        final_filename_parts = [base_ep_filename]
        if new_edition != "{edition-Theatrical Cut}": final_filename_parts.append(f" {new_edition}")

        final_ep_filename = "".join(final_filename_parts) + ep_ext
        final_ep_path = os.path.join(season_dest_dir, final_ep_filename)
        final_media_paths[episode_path] = final_ep_path

        if not os.path.exists(final_ep_path):
            logging.info(f"Copying new episode version: {final_ep_filename}")
            shutil.copy2(episode_path, final_ep_path)
        else:
             logging.warning(f"Version '{final_ep_filename}' already exists. Skipping.")

    process_subtitles(subtitle_files, final_media_paths)


def process_bundle(bundle_path):
    """Orchestrator that analyzes a bundle and calls the correct processor."""
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
    """Handles logic for a single media file dropped directly into the watch folder."""
    logging.info(Fore.CYAN + f"--- Processing Single File: {os.path.basename(filepath)} ---")
    parsed_info = parse_filename(os.path.basename(filepath))

    media_type_hint = "series" if parsed_info.get("season") else "movie"
    metadata = search_tvdb_metadata(parsed_info, media_type=media_type_hint)

    if not metadata:
        logging.error(f"Could not find metadata for file '{os.path.basename(filepath)}'. Skipping.")
        return

    if metadata['type'] == 'series':
        process_tv_season_bundle(filepath, metadata, [(filepath, os.path.basename(filepath))], [])
    elif metadata['type'] == 'movie':
        process_movie_bundle(filepath, metadata, [(filepath, os.path.basename(filepath))], [], [])

    safe_remove(filepath, is_source_bundle=True)
