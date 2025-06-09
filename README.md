# Orz - Automated Media Organizer for Plex

Orz is a powerful, automated media organizer designed to work seamlessly with Plex. It watches a directory for new downloads, intelligently identifies them as movies or TV shows, fetches metadata from TheTVDB, and renames and organizes them into a clean, Plex-compliant library structure.

The script runs continuously in a Docker container, making it a "set it and forget it" solution for maintaining a tidy media library.

---

## Key Features

- **Automated Directory Watching**: No more manual script execution. Orz automatically detects new video files and begins processing them.
- **Intelligent Metadata Matching**: Uses fuzzy string matching (`thefuzz`) and a confidence score to accurately identify movies and TV shows, significantly reducing mismatches.
- **Quality-Based Upgrades**: Automatically replaces existing media files with higher-quality versions. It can compare a new `1080p` file against an existing `720p` file and perform an upgrade.
- **Reliable Quality Detection**: Uses `ffprobe` to read a video's true resolution directly from its metadata stream. This works even if your existing library files don't have quality keywords in their names.
- **Plex-Compliant Naming**: Creates filenames and directory structures that follow Plex's official naming conventions for movies, TV shows, seasons, and episodes.
- **Extras & Subtitle Handling**: Intelligently identifies and organizes supplementary files like featurettes, deleted scenes, interviews, and subtitles into the correct subdirectories for Plex.
- **Containerized with Docker**: Packaged with all its dependencies in a Docker container for easy, one-command deployment.
- **Robust Error Handling**: Problematic files that can't be matched are moved to a `failed` directory for manual review, preventing the script from getting stuck.

---

## Prerequisites

Before you begin, ensure you have the following installed on your system:

- **Git** (for cloning the repository)
- **Docker** and **Docker Compose** (for running the application)

---

## Setup and Installation

Follow these steps to get Orz up and running.

**1. Clone the Repository**
```bash
git clone [https://github.com/ahmedkay9/orz.git](https://github.com/ahmedkay9/orz.git)
cd orz
```

**2. Create the Environment File**
Create a file named `.env` in the root of the project directory. This file will store your secret API key. Add the following line, replacing `YOUR_KEY_HERE` with your actual key from TheTVDB.

```
TVDB_API_KEY=YOUR_KEY_HERE
```

**3. Configure Media Paths**
Open the `docker-compose.yml` file. You need to tell Docker where your media is located. Edit the `volumes` section to map your host machine's directories to the directories inside the container.

- **For Production on a Server:**
  Replace the example paths with the *actual* paths to your downloads and Plex library.
  ```yaml
  volumes:
    # Path to your completed downloads folder : Path inside the container
    - /path/to/your/downloads/completed:/watch
    # Path to your Plex library root : Path inside the container
    - /path/to/your/plex/library:/data
  ```

- **For Local Testing:**
  You can use local folders to test without affecting your real library.
  ```yaml
  volumes:
    - ./test-watch:/watch
    - ./test-data:/data
  ```

---

## Usage

**Running the Application**

Navigate to the project directory in your terminal and run the following command:

```bash
docker-compose up --build -d
```
- `--build`: This flag is only needed the first time you run it or after making changes to the code or `Dockerfile`.
- `-d`: Runs the container in "detached" mode (in the background), so it will keep running even after you close your terminal.

That's it! Orz is now watching your `/watch` directory for new content.

**Viewing Logs**
To see what the script is doing in real-time, you can view its logs:
```bash
docker-compose logs -f
```
Press `Ctrl + C` to stop viewing the logs.

**Stopping the Application**
To stop the container, run:
```bash
docker-compose down
```

---

## How It Works

1. **Watch**: The `watchdog` library monitors the `/watch` source directory for new files.

2. **Identify**: When a new file appears, the script identifies the primary video file in the download and scans for associated extras (other videos, subtitles).

3. **Parse & Search**: It parses the filename to extract the title, year, and episode information. It then searches TheTVDB and uses a fuzzy matching algorithm to find the best metadata match.

4. **Compare & Upgrade**: If a version of the file already exists in the destination library, the script uses `ffprobe` to compare the quality of the new and existing files, performing an upgrade if necessary.

5. **Copy & Organize**: The script copies the main video file and all its associated extras and subtitles to the destination `/data` directory, creating the proper Plex-compliant folder structure (e.g., `/TV Shows/Show Name (Year)/Season 01/`).

6. **Repeat**: The script continues watching for the next new file.
