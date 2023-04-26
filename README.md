# Travian Bot

Travian Bot to keep an eye on your account. Build, defend and attack while you're offline.

## Settings

```bash
chmod +x env.sh
chmod +x deploy.sh

# Set up environment variables
./env.sh

# Create web_network
docker network create web_network
```

## Run

```bash
# Install dependencies
pip install --upgrade pip
pip install --no-cache-dir --upgrade -r requirements.txt

# Run bot locally
./env.sh && python bot/bot.py
```

## Deploy (Docker)

```bash
# Build and run all containers
./deploy.sh

# Stop all containers
docker-compose down
```

## Bot

```bash
# Build and run bot
./deploy.sh --build travian-bot

# Sync changes
docker-compose restart travian-bot

# Refresh bot container (without build)
./deploy.sh --no-deps travian-bot

# Refresh bot container (with build for pip install)
./deploy.sh --no-deps --build travian-bot

# Watch logs
docker logs travian-bot -f --tail 1000

# Stop bot
docker stop travian-bot
```
