import logging

LOG_LEVEL = logging.WARN

DATE_TIME_FORMAT = '%Y-%m-%d %H:%M:%S'


def set_logging(level=LOG_LEVEL):
    global LOG_LEVEL
    LOG_LEVEL = level

    logging.basicConfig(
        format='%(asctime)s  %(levelname)s\t[%(name)s]  %(message)s', level=level)

    if level == logging.INFO:
        logging.getLogger("telegram.ext.dispatcher").setLevel(logging.WARN)
        logging.getLogger("apscheduler.scheduler").setLevel(logging.WARN)
        logging.getLogger("apscheduler.executors.default").setLevel(logging.WARN)
        logging.getLogger("pyppeteer.launcher").setLevel(logging.WARN)

    if level == logging.DEBUG:
        logging.getLogger("asyncio").setLevel(logging.INFO)
        logging.getLogger("websockets.client").setLevel(logging.INFO)
        logging.getLogger("pyppeteer.connection").setLevel(logging.INFO)
        import pyppeteer
        pyppeteer.DEBUG = True  # print suppressed errors as error log

    logging.info(f"Set log level {logging.getLevelName(logging.root.level)}")


def console_log(logger: logging.Logger, message_type: str, message: str):
    log = logger.debug if message_type == 'verbose' else getattr(logger, message_type)
    log(message)


def load_environment():
    from dotenv import load_dotenv
    load_dotenv()


def format_date(datetime):
    return datetime.strftime(DATE_TIME_FORMAT)
