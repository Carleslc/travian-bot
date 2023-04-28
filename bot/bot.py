#!/usr/bin/python3
# -*- coding: utf-8 -*-

import os
import logging

from settings import set_logging, load_environment

from travian.bot import start_travian_bot
from travian.errors import run_handle_interrupt

if __name__ == '__main__':
    load_environment()

    set_logging(logging.DEBUG)

    TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")

    logging.info("Starting bot...")

    run_handle_interrupt(start_travian_bot)

    logging.info("Goodbye!")
