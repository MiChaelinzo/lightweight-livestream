"""Opt-in secure storage for the stream key.

Nothing here runs unless the person asks for it. The key is handed to an
operating system facility; if none exists the save is REFUSED. There is no
plaintext fallback, and the key is never written to config.json.

Backends
    Windows  DPAPI (CryptProtectData through ctypes). The encrypted blob is
             saved next to config.json (mode 0600) and only the same Windows
             user can decrypt it.
    macOS    the `security` command (login keychain). The secret is sent on
             stdin to `security -i`, not placed in argv.
    Linux    `secret-tool` (libsecret) when installed; the secret goes on stdin.

Status: all three backends are UNVERIFIED on real systems (this code was
written and tested on Linux without secret-tool). Unit tests use injected
fakes and only prove the control flow: opt-in, refusal, no config leak, and
the exact commands issued. Windows DPAPI protects against other users, not
against malware running as the same user. Keychain and Secret Service entries
may be readable by other programs of the same user after the first unlock.
"""

import base64
import os
import shutil
import subprocess

SERVICE = "lightstream"
ACCOUNT = "stream-key"
BLOB_FILENAME = "stream-key.dpapi"
SECRET_TOOL = "secret-tool"
SECURITY_TOOL = "security"
COMMAND_TIMEOUT_SECONDS = 15


class SecureStoreError(Exception):
    """Base class. Messages never contain the secret."""


class SecureStoreUnavailable(SecureStoreError):
    """No secure backend on this system. Nothing was saved."""


class OptInRequired(SecureStoreError):
    """The person has not opted in to saving the key. Nothing was saved."""


class NotFound(SecureStoreError):
    """No saved key."""


def _check_secret(secret):
    if not isinstance(secret, str) or not secret.strip():
        raise ValueError("The stream key is empty")
    if "\n" in secret or "\r" in secret or "\x00" in secret:
        raise ValueError("The stream key must be a single line")


class SecretToolBackend:
    """Linux libsecret through the `secret-tool` program. UNVERIFIED."""
    name = "secret-tool"

    def __init__(self, run=subprocess.run, program=SECRET_TOOL):
        self._run = run
        self._program = program

    def _attrs(self):
        return ["service", SERVICE, "account", ACCOUNT]

    def save(self, secret):
        proc = self._run([self._program, "store", "--label=LightStream stream key"]
                         + self._attrs(), input=secret + "\n", capture_output=True,
                         text=True, timeout=COMMAND_TIMEOUT_SECONDS)
        if proc.returncode != 0:
            raise SecureStoreError("secret-tool could not save the key (exit %s)"
                                   % proc.returncode)

    def load(self):
        proc = self._run([self._program, "lookup"] + self._attrs(),
                         capture_output=True, text=True,
                         timeout=COMMAND_TIMEOUT_SECONDS)
        if proc.returncode != 0 or not proc.stdout.strip():
            raise NotFound("no saved stream key")
        return proc.stdout.strip()

    def delete(self):
        self._run([self._program, "clear"] + self._attrs(), capture_output=True,
                  text=True, timeout=COMMAND_TIMEOUT_SECONDS)


class MacKeychainBackend:
    """macOS login keychain through `security -i` (stdin script). UNVERIFIED."""
    name = "macos-keychain"

    def __init__(self, run=subprocess.run, program=SECURITY_TOOL):
        self._run = run
        self._program = program

    def save(self, secret):
        # Quote for the `security -i` line parser: no quotes or backslashes allowed.
        if '"' in secret or "\\" in secret:
            raise ValueError("The macOS keychain backend cannot store a key "
                             "containing quotes or backslashes")
        script = ('add-generic-password -a "%s" -s "%s" -w "%s" -U\n'
                  % (ACCOUNT, SERVICE, secret))
        proc = self._run([self._program, "-i"], input=script, capture_output=True,
                         text=True, timeout=COMMAND_TIMEOUT_SECONDS)
        if proc.returncode != 0:
            raise SecureStoreError("security could not save the key (exit %s)"
                                   % proc.returncode)

    def load(self):
        proc = self._run([self._program, "find-generic-password", "-a", ACCOUNT,
                          "-s", SERVICE, "-w"], capture_output=True, text=True,
                         timeout=COMMAND_TIMEOUT_SECONDS)
        if proc.returncode != 0 or not proc.stdout.strip():
            raise NotFound("no saved stream key")
        return proc.stdout.strip()

    def delete(self):
        self._run([self._program, "delete-generic-password", "-a", ACCOUNT,
                   "-s", SERVICE], capture_output=True, text=True,
                  timeout=COMMAND_TIMEOUT_SECONDS)


def _windows_protect(data):  # UNVERIFIED: needs a Windows machine
    import ctypes
    from ctypes import wintypes

    class Blob(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD),
                    ("pbData", ctypes.POINTER(ctypes.c_char))]

    source = ctypes.create_string_buffer(data, len(data))
    inblob = Blob(len(data), ctypes.cast(source, ctypes.POINTER(ctypes.c_char)))
    outblob = Blob()
    if not ctypes.windll.crypt32.CryptProtectData(
            ctypes.byref(inblob), "LightStream", None, None, None, 0,
            ctypes.byref(outblob)):
        raise SecureStoreError("Windows DPAPI could not encrypt the key")
    try:
        return ctypes.string_at(outblob.pbData, outblob.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(outblob.pbData)


def _windows_unprotect(data):  # UNVERIFIED: needs a Windows machine
    import ctypes
    from ctypes import wintypes

    class Blob(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD),
                    ("pbData", ctypes.POINTER(ctypes.c_char))]

    source = ctypes.create_string_buffer(data, len(data))
    inblob = Blob(len(data), ctypes.cast(source, ctypes.POINTER(ctypes.c_char)))
    outblob = Blob()
    if not ctypes.windll.crypt32.CryptUnprotectData(
            ctypes.byref(inblob), None, None, None, None, 0, ctypes.byref(outblob)):
        raise SecureStoreError("Windows DPAPI could not decrypt the saved key")
    try:
        return ctypes.string_at(outblob.pbData, outblob.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(outblob.pbData)


class DpapiBackend:
    """Windows DPAPI. The encrypted blob lives in blob_path (mode 0600)."""
    name = "windows-dpapi"

    def __init__(self, blob_path, protect=_windows_protect,
                 unprotect=_windows_unprotect):
        self._path = blob_path
        self._protect = protect
        self._unprotect = unprotect

    def save(self, secret):
        from .fileio import write_private_text
        blob = self._protect(secret.encode("utf-8"))
        os.makedirs(os.path.dirname(os.path.abspath(self._path)), exist_ok=True)
        write_private_text(self._path, base64.b64encode(blob).decode("ascii") + "\n")

    def load(self):
        try:
            with open(self._path, "r", encoding="ascii") as fh:
                blob = base64.b64decode(fh.read().strip())
        except FileNotFoundError:
            raise NotFound("no saved stream key")
        return self._unprotect(blob).decode("utf-8")

    def delete(self):
        try:
            os.unlink(self._path)
        except FileNotFoundError:
            pass


def select_backend(os_name, config_dir, which=shutil.which, run=subprocess.run):
    """The backend for this OS, or None when there is none. Never a file fallback."""
    if os_name == "windows":
        return DpapiBackend(os.path.join(config_dir, BLOB_FILENAME))
    if os_name == "macos":
        return MacKeychainBackend(run) if which(SECURITY_TOOL) else None
    if os_name == "linux":
        return SecretToolBackend(run) if which(SECRET_TOOL) else None
    return None


class SecureKeyStore:
    """Save, load and forget the stream key. Saving needs opt_in=True AND a backend."""

    def __init__(self, backend):
        self._backend = backend

    @property
    def backend_name(self):
        return self._backend.name if self._backend else None

    def available(self):
        return self._backend is not None

    def save(self, secret, opt_in=False):
        if not opt_in:
            raise OptInRequired("Saving the stream key is off. Opt in explicitly "
                                "to store it in the system credential store.")
        if self._backend is None:
            raise SecureStoreUnavailable(
                "No secure credential store was found on this system, so the "
                "stream key was NOT saved. LightStream never stores it in a plain "
                "file. Type it or set STREAM_KEY each time.")
        _check_secret(secret)
        self._backend.save(secret.strip())

    def load(self):
        if self._backend is None:
            raise SecureStoreUnavailable("No secure credential store on this system")
        return self._backend.load()

    def forget(self):
        if self._backend is not None:
            self._backend.delete()
