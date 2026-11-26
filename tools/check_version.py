"""Check that package metadata, runtime version, and an optional tag agree."""

import argparse
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from lightstream import __version__  # noqa: E402

VERSION_LINE = re.compile(r'^version\s*=\s*["\']([^"\']+)["\']\s*(?:#.*)?$')


class VersionError(ValueError):
    pass


def read_project_version(path=None):
    """Read ``project.version`` without adding a TOML dependency on Python 3.8."""
    path = path or os.path.join(ROOT, "pyproject.toml")
    section = None
    with open(path, "r", encoding="utf-8") as handle:
        for raw_line in handle:
            line = raw_line.strip()
            if line.startswith("[") and line.endswith("]"):
                section = line
                continue
            if section == "[project]":
                match = VERSION_LINE.match(line)
                if match:
                    return match.group(1)
    raise VersionError("[project].version was not found in %s" % path)


def check_versions(expected=None, project_file=None, runtime_version=None):
    runtime = __version__ if runtime_version is None else runtime_version
    project = read_project_version(project_file)
    if runtime != project:
        raise VersionError("runtime version %s does not match pyproject version %s" %
                           (runtime, project))
    if expected is not None and expected != runtime:
        raise VersionError("expected version %s does not match package version %s" %
                           (expected, runtime))
    return runtime


def main(argv=None, out=None, err=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expect", help="also require this exact version (tag without v)")
    parser.add_argument("--pyproject", help="alternate pyproject.toml for validation")
    args = parser.parse_args(argv)
    out = out or sys.stdout
    err = err or sys.stderr
    try:
        version = check_versions(args.expect, args.pyproject)
    except (OSError, VersionError) as exc:
        err.write("version check failed: %s\n" % exc)
        return 1
    out.write("LightStream version %s matches runtime and pyproject metadata.\n" % version)
    return 0


if __name__ == "__main__":
    sys.exit(main())
