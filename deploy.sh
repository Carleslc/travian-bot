#!/bin/bash

# Exit on error
set -e

echo "Loading .env"

./env.sh

# Docker Compose command
docker_compose="docker compose"

if ! $docker_compose &> /dev/null; then
    # Legacy command
    docker_compose="docker-compose"
fi

echo "Running containers"

args="$*"

if [ ! -z "$args" ]; then
    # With arguments
    if [[ $1 == -* ]]; then
        # Custom options
        echo "$docker_compose up -d $args"
        $docker_compose up -d $args
    else
        # Container refresh
        echo "$docker_compose up --force-recreate -d $args"
        $docker_compose up --force-recreate -d $args
    fi
else
    # Without arguments, deploy all
    echo "$docker_compose up --build -d"
    $docker_compose up --build -d
fi
