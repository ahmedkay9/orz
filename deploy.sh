#!/bin/bash

# Load variables from .env file
if [ -f .env ]; then
    export $(egrep -v '^#' .env | xargs)
else
    echo ".env file not found!"
    exit 1
fi

# Step 1: Sync files to the server
rsync -avz --exclude 'deploy.sh' --exclude '.venv/' --exclude '.git/' --exclude '__pycache__/' $LOCAL_PATH $SERVER_USER@$SERVER_HOST:$SERVER_PATH

# Step 2: SSH into the server and execute commands
ssh -T $SERVER_USER@$SERVER_HOST << EOF
cd $SERVER_PATH
./orz/.venv/bin/pip install -r orz/requirements.txt
# Use ./orz/.venv/bin/python to run Python scripts or commands
echo "Deployment and setup complete."
EOF