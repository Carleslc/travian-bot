from typing import Callable


class AuthenticationError(Exception):
    pass


def run_handle_interrupt(f: Callable[[], None]):
    try:
        f()
    except KeyboardInterrupt:
        pass  # Ctrl^C
