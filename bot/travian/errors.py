class AuthenticationError(Exception):
    pass


def run_handle_interrupt(f):
    try:
        f()
    except KeyboardInterrupt:
        pass  # Ctrl^C
