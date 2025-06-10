# Use an official lightweight Python runtime as a parent image
FROM python:3.11-slim

# Set environment variables to prevent Python from writing .pyc files
ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1

# Set the working directory inside the container
WORKDIR /app

# Install ffmpeg, which provides the ffprobe command-line tool
RUN apt-get update && apt-get install -y ffmpeg && rm -rf /var/lib/apt/lists/*

# Copy the requirements file into the container
COPY requirements.txt .

# Install dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy the application code into the container
COPY config.py .
COPY utils.py .
COPY metadata.py .
COPY processor.py .
COPY orz_watcher.py .
COPY .env .

# The command that will be run when the container starts
CMD ["python", "orz_watcher.py"]
