#!/bin/bash

# Load variables from .env file
if [ -f .env ]; then
    export $(egrep -v '^#' .env | xargs)
else
    echo ".env file not found!"
    exit 1
fi

# Step 1: Sync files to the server
rsync -avz --exclude 'deploy.sh' --exclude '.env' --exclude '.gitignore' --exclude '.venv/' --exclude '.git/' --exclude '__pycache__/' $LOCAL_PATH $SERVER_USER@$SERVER_HOST:$SERVER_PATH

# Step 2: SSH into the server and execute commands
ssh $SERVER_USER@$SERVER_HOST << EOF
cd $SERVER_PATH
source venv/bin/activate
pip install -r requirements.txt
echo "Deployment and setup complete."
EOF