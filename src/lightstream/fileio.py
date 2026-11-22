"""Small file helpers. Private files are written atomically with mode 0600."""

import os
import tempfile

PRIVATE_MODE = 0o600


def write_private_text(path, text):
    """Write text to path through a temp file and os.replace.

    A crash mid-write leaves the old file intact. On POSIX the file is
    created with mode 0600 (owner only). Windows ignores POSIX modes, so
    there the chmod is a harmless no-op. The file is not fsynced, so this
    protects against a process crash, not against power loss.
    """
    directory = os.path.dirname(os.path.abspath(path))
    fd, tmp = tempfile.mkstemp(dir=directory, prefix=".tmp-", suffix=".part")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
        try:
            os.chmod(tmp, PRIVATE_MODE)
        except OSError:
            pass  # filesystems without POSIX modes
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def create_private_text(path, text):
    """Create a new file with mode 0600. Raises FileExistsError if present.

    If the write fails, the partial file is removed so it cannot block the
    filename. A hard kill mid-write can still leave a partial file.
    """
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, PRIVATE_MODE)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
    except BaseException:
        try:
            os.unlink(path)
        except OSError:
            pass
        raise
