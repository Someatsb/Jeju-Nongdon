"""Pre-commit secret scan for the jeju-chaenggim tree.

Usage (from jeju-chaenggim/):  python -I scripts/check_secrets.py
Clean: prints "OK 0 hits", exit 0.  Hits: prints "path:line: token" per hit
(never the rest of the line, so a real key is not echoed), then "FAIL n hits", exit 1.
Paths ignored by jeju-chaenggim/.gitignore are skipped; they are never committed.
"""
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Joined from pieces so this file does not match its own pattern.
TOKENS = ("sk-" + "ant-", "project" + "Key=", "access" + "Token")
# Extra words to look for on this PC only (account ids and the like): one per line in
# ~/.jeju-chaenggim/private_tokens.txt. The file is optional and never part of the project.
PRIVATE_FILE = os.path.join(os.path.expanduser("~"), ".jeju-chaenggim", "private_tokens.txt")


def private_tokens(path=PRIVATE_FILE):
    try:
        with open(path, encoding="utf-8-sig") as f:
            return tuple(t for t in (ln.strip() for ln in f) if t and t.isascii() and not t.startswith("#"))
    except OSError:
        return ()


TOKENS = TOKENS + private_tokens()
PATTERN = re.compile("|".join(re.escape(t) for t in TOKENS).encode("ascii"))
# Mobile-number shape. Only the two fake numbers used in tests and help text are allowed.
PHONE = re.compile(rb"010-[0-9]{4}-[0-9]{4}")
PHONE_OK = {b"010-1234-5678", b"010-0000-0000"}

SKIP_DIRS = {".git", "__pycache__", ".pytest_cache", "logs", "runtime",
             "data/live", "data/inbox", "data/backup", "data/reminders"}
SKIP_FILES = {".env"}
SKIP_SUFFIXES = (".pyc",)


def iter_files(root):
    for dirpath, dirnames, filenames in os.walk(root):
        rel_dir = os.path.relpath(dirpath, root).replace(os.sep, "/")
        rel_dir = "" if rel_dir == "." else rel_dir + "/"
        dirnames[:] = sorted(d for d in dirnames
                             if d not in SKIP_DIRS and rel_dir + d not in SKIP_DIRS)
        for name in sorted(filenames):
            if name in SKIP_FILES or name.endswith(SKIP_SUFFIXES):
                continue
            yield rel_dir + name, os.path.join(dirpath, name)


def scan(root):
    hits = []
    for rel, full in iter_files(root):
        with open(full, "rb") as f:
            for lineno, line in enumerate(f, start=1):
                m = PATTERN.search(line)
                if m:
                    hits.append((rel, lineno, m.group().decode("ascii")))
                for pm in PHONE.finditer(line):
                    if pm.group() not in PHONE_OK:
                        hits.append((rel, lineno, "phone-number"))     # never echo the number itself
    return hits


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="backslashreplace")
    hits = scan(ROOT)
    for rel, lineno, token in hits:
        print(f"{rel}:{lineno}: {token}")
    if hits:
        print(f"FAIL {len(hits)} hits")
        return 1
    print("OK 0 hits")
    return 0


if __name__ == "__main__":
    sys.exit(main())
