#!/bin/bash

env=".env"

if [ "$1" != "" ]; then
    env="$1"
fi

config="config.yml"
config_template="config.template.yml"

if [ ! -f "$config" ]; then
    cp "$config_template" "$config"

    echo "$config created"
fi

if [ ! -f "$env" ]; then
    cp "$env.template" "$env"

    echo "$env"

    echo "Please, fill the $env file"

    exit 1
fi

set -o allexport
# https://gist.github.com/judy2k/7656bfe3b322d669ef75364a46327836
eval $(cat "$env" | sed -e '/^#/d;/^\s*$/d' -e 's/\(\w*\)[ \t]*=[ \t]*\(.*\)/\1=\2/' -e "s/=['\"]\(.*\)['\"]/=\1/g" -e "s/'/'\\\''/g" -e "s/=\(.*\)/='\1'/g")
set +o allexport
