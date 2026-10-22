"""Keep Gmsh native initialization from changing Python's broken-pipe policy."""
import signal


def _call(operation):
    pipe = getattr(signal, 'SIGPIPE', None)
    handler = signal.getsignal(pipe) if pipe is not None else None
    try:
        return operation()
    finally:
        # Gmsh can reset the native handler without updating Python's cached
        # getsignal() value. Reinstall the caller's policy, not an assumed SIG_IGN.
        if pipe is not None:
            signal.signal(pipe, handler)


def initialize():
    import gmsh
    return _call(gmsh.initialize)


def finalize():
    import gmsh
    return _call(gmsh.finalize)
