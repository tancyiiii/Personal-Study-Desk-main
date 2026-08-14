import os
import sys


def resource_path(relative_path: str) -> str:
    """Return a path that works both from source and from a frozen EXE."""
    if getattr(sys, "frozen", False):
        exe_dir = os.path.dirname(sys.executable)
        external = os.path.join(exe_dir, relative_path)
        if os.path.exists(external):
            return external
        return os.path.join(sys._MEIPASS, relative_path)
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), relative_path)
