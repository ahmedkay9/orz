# Orzy - Automated Media Organizer

Orzy is a powerful, automated media organizer designed to watch a source directory for new movie and TV show files, identify them using TheTVDB, and then rename and organize them into a clean, Plex-compliant library structure.

The script is built to be robust, handling entire media bundles (e.g., a movie with all its featurettes, or a full season of a TV show) as a single atomic unit. It intelligently supports multiple versions and editions of the same media, ensuring your library is both complete and non-destructive.

## Key Features

* **Automated Directory Watching**: Continuously monitors a source directory for new media using a file system watcher.
* **Intelligent Bundle Processing**: Treats a directory containing a movie or TV season as a single "bundle." It waits for the entire directory to be copied before processing, preventing errors with large or slow transfers.
* **Plex-Compliant Naming**: Renames files and structures directories according to Plex's official naming conventions for movies, TV shows, extras, and subtitles.
* **TVDB Metadata Integration**: Accurately identifies media by searching TheTVDB API, including robust handling for foreign films with English titles.
* **Non-Destructive & Multi-Version Support**:
    * **Never deletes existing files** in your destination library.
    * If a better quality version of a file arrives, it is added alongside the existing one.
    * If a lower quality version arrives, it is intelligently ignored to prevent clutter.
* **Editions Support**: Automatically detects and tags different editions of a film or episode (e.g., `Superfan Cut`, `Director's Cut`, `Theatrical`) according to Plex guidelines.
* **Comprehensive File Handling**:
    * Processes both single media files and full directory bundles.
    * Correctly identifies and organizes special features like featurettes, deleted scenes, gag reels, and trailers into appropriate subfolders.
    * Parses and renames subtitle files to match their corresponding media files, including language and forced/SDH tags.
* **Robust and Resilient**: Built with a queueing system and error handling that prevents the application from crashing on a single failed file.
* **Dockerized**: Runs as a self-contained Docker service for easy deployment and dependency management.
* **Highly Configurable**: All major settings, including API keys, directories, and filename parsing keywords, are managed through a `.env` file and a central `config.py` file for easy customization.

## Requirements

* Python 3.11+
* Docker & Docker Compose
* An API key from [TheTVDB](https://www.thetvdb.com/subscribe)
* All Python dependencies as listed in `requirements.txt`
* **System Dependency**: The application requires `ffmpeg` to be installed (which provides `ffprobe`) for video quality analysis. This is handled automatically within the provided `Dockerfile`.

## Setup & Configuration

1.  **Clone the Repository**:
    ```bash
    git clone [your-repo-url]
    cd [your-repo-directory]
    ```

2.  **Create an Environment File**: Copy the example environment file to create your own configuration.
    ```bash
    cp .env.example .env
    ```

3.  **Edit the `.env` file**: Open the newly created `.env` file and fill in the required values:
    * `TVDB_API_KEY`: Your personal API key from TheTVDB.
    * `SOURCE_DIR`: The directory the script will watch for new media (e.g., `./test_watch`).
    * `DEST_BASE_DIR`: The base directory where your organized `tv` and `movies` libraries will be created (e.g., `./test_data`).
    * `DELETE_SOURCE_FILES`: Set to `true` to delete the source files/folders after successful processing, or `false` (default) to leave them untouched.

4.  **(Optional) Customize Keywords**: For advanced customization, you can edit the dictionaries in `config.py` to add or change keywords for detecting editions, versions, and extras.

## Running with Docker

The application is designed to be run as a Docker container for simplicity and portability.

1.  **Build the Docker Image**:
    ```bash
    docker-compose build
    ```
    *(The first time you run this, it will download the Python base image and install ffmpeg, which may take a few minutes. Subsequent builds will be much faster.)*

2.  **Start the Service**:
    ```bash
    docker-compose up -d
    ```
    This will start the `orzy-watcher` service in the background.

3.  **Viewing Logs**: To see the real-time output of the script, including colored warnings and errors, use the following command:
    ```bash
    docker-compose logs -f
    ```

4.  **Stopping the Service**:
    ```bash
    docker-compose down
    ```

## How It Works

The script's architecture is designed for robustness and reliability:

1.  **Watch**: The `ChangeHandler` in `orzy_watcher.py` monitors the `SOURCE_DIR` for any file creation or modification.
2.  **Debounce & Queue**: When an event is detected, it doesn't act immediately. It starts a short timer (`PROCESS_DELAY`). If more file events occur for the same item (e.g., a large directory being copied), the timer resets. Once the item is "quiet," its path is added to a central processing queue.
3.  **Stability Check**: The `worker` thread pulls an item from the queue and begins an active stability check, ensuring the file or directory's contents are no longer changing before proceeding.
4.  **Analyze & Process**: The item is passed to a processor which classifies it as a movie, TV show, single file, or bundle. It fetches metadata, compares versions, and moves all related files (main feature, extras, subtitles) to their final destination in one atomic operation.

This bundle-based, non-destructive approach ensures that your media library is organized correctly and safely, even when dealing with complex, multi-file media.

