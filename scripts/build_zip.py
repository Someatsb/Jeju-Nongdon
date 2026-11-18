"""Build the submission zip (--g1 = rehearsal zip of Task 33, --final = 11-13 submission zip of Task 37).

Usage (from jeju-chaenggim/):  python -X utf8 scripts/build_zip.py --g1|--final [--out DIR]
--final writes dist/jeju-nongdon-submit-1120.zip with RELEASE.txt at the top folder, refuses unless tests/REPORT.txt is newer
than the last commit touching app/ or data/ and says "golden 12 passed", and re-opens the zip to verify every MANIFEST hash.
Refuses to build unless check_secrets prints "OK 0 hits" and no .env is tracked by git.
Writes dist/jeju-nongdon-g1-<yyyymmdd>.zip; everything sits under one top folder jeju-nongdon/ with MANIFEST.sha256 inside it.
Refuses on a dirty git tree unless --allow-dirty, and on any .env* file under the tree.
"""
import argparse
import datetime
import hashlib
import os
import subprocess
import sys
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WARN_MB = 300
LIMIT_MB = 500

TOP = "jeju-nongdon"     # one ASCII top folder so an unzip never spills files into the current folder
VERSION = "v1.0-submit-1120"
FINAL_NAME = "jeju-nongdon-submit-1120.zip"
ROOT_DIRS = ("logs", "dist", "research", ".superpowers", "data/live", "data/reminders", "data/backup", "data/hub")
CACHE_NAMES = {"__pycache__", ".pytest_cache"}
EXCLUDE_NAMES = {"catalog-analyzed.csv", ".junit.xml"}
KEEP_ALWAYS = {"data/inbox/.gitkeep"}


def norm(rel: str) -> str:
    rel = rel.replace("\\", "/").lstrip("/")
    while rel.startswith("./"):
        rel = rel[2:]
    return rel.lower()


def excluded(rel: str, is_dir: bool = False) -> bool:
    """Case-insensitive (NTFS), separator-agnostic. Root-only entries are anchored; caches and secrets match at any depth."""
    rel = norm(rel)
    if rel in KEEP_ALWAYS:
        return False
    parts = rel.split("/")
    if any(p in CACHE_NAMES or p.startswith(".env") or p.startswith(".git") for p in parts):
        return True
    if any(rel == d or rel.startswith(d + "/") for d in ROOT_DIRS):
        return True
    if is_dir:
        return False
    name = parts[-1]
    return (rel.startswith("data/inbox/") or name in EXCLUDE_NAMES or name.endswith((".pyc", ".xlsx"))
            or (name.startswith("869_") and name.endswith(".csv")))


def collect() -> list[str]:
    out = []
    for dirpath, dirnames, filenames in os.walk(ROOT):
        rel_dir = os.path.relpath(dirpath, ROOT).replace(os.sep, "/")
        rel_dir = "" if rel_dir == "." else rel_dir
        keep = []
        for d in sorted(dirnames):
            rel = (rel_dir + "/" + d).lstrip("/")
            full = os.path.join(dirpath, d)
            if excluded(rel, True):
                continue
            if os.path.islink(full) or (hasattr(os.path, "isjunction") and os.path.isjunction(full)):
                print("WARNING: link/junction skipped: " + rel)
                continue
            keep.append(d)
        dirnames[:] = keep
        for f in sorted(filenames):
            rel = (rel_dir + "/" + f).lstrip("/")
            if excluded(rel):
                continue
            if os.path.islink(os.path.join(dirpath, f)):
                print("WARNING: symlink skipped: " + rel)
                continue
            out.append(rel)
    return out


def find_env_files(root=ROOT) -> list[str]:
    """Any .env* file or folder under the tree, tracked or not, in any case. Paths only, never contents."""
    hits = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d.lower() != ".git"]
        for n in filenames + dirnames:
            if n.lower().startswith(".env"):
                hits.append(os.path.relpath(os.path.join(dirpath, n), root).replace(os.sep, "/"))
    return sorted(hits)


def env_names(names) -> list[str]:
    """Names (zip members or paths) with any .env* component, in any case."""
    return sorted(n for n in names if any(p.lower().startswith(".env") for p in n.replace("\\", "/").split("/")))


def out_dir_ok(out, root=ROOT) -> bool:
    """Outside the tree, or under <root>/dist (which is never packed)."""
    out, root = os.path.realpath(out), os.path.realpath(root)
    dist = os.path.join(root, "dist")
    inside = lambda p, base: os.path.normcase(p) == os.path.normcase(base) or         os.path.normcase(p).startswith(os.path.normcase(base) + os.sep)
    return inside(out, dist) or not inside(out, root)


def write_zip(entries, zpath, extras=()) -> int:
    """entries: [(rel, full path)]; extras: [(rel, bytes)] generated files (RELEASE.txt). Each file is read once; the same bytes are hashed and written."""
    lines = []
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for rel, full in entries:
            with open(full, "rb") as fh:
                data = fh.read()
            lines.append("%s  %s" % (hashlib.sha256(data).hexdigest(), rel))
            z.writestr(zipfile.ZipInfo.from_file(full, TOP + "/" + rel), data, zipfile.ZIP_DEFLATED, 6)
        for rel, data in extras:
            lines.append("%s  %s" % (hashlib.sha256(data).hexdigest(), rel))
            zi = zipfile.ZipInfo(TOP + "/" + rel, datetime.datetime.now().timetuple()[:6])
            z.writestr(zi, data, zipfile.ZIP_DEFLATED, 6)
        z.writestr(TOP + "/MANIFEST.sha256", "\n".join(lines) + "\n")
    return len(entries) + len(extras) + 1


def verify_zip(zpath) -> int:
    """Re-open the finished zip and check every MANIFEST hash and that no file is missing or unlisted. Returns the number of files checked."""
    with zipfile.ZipFile(zpath) as z:
        bad = z.testzip()
        if bad:
            sys.exit("VERIFY FAILED: corrupt member " + bad)
        listed = {}
        for ln in z.read(TOP + "/MANIFEST.sha256").decode("utf-8").splitlines():
            h, rel = ln.split("  ", 1)
            listed[rel] = h
        names = {n[len(TOP) + 1:] for n in z.namelist() if not n.endswith("/")} - {"MANIFEST.sha256"}
        if names != set(listed):
            sys.exit("VERIFY FAILED: manifest and zip differ: %s" % sorted(names ^ set(listed))[:5])
        for rel, h in listed.items():
            if hashlib.sha256(z.read(TOP + "/" + rel)).hexdigest() != h:
                sys.exit("VERIFY FAILED: hash mismatch " + rel)
    return len(listed)


def _git(*a) -> str:
    r = subprocess.run(["git", *a], cwd=ROOT, capture_output=True, text=True, encoding="utf-8")
    if r.returncode != 0:
        sys.exit("REFUSED: git %s failed" % " ".join(a))
    return r.stdout.strip()


def check_report() -> str:
    """REPORT.txt must be newer than the last commit touching app/ or data/ and show golden 12 passed. Returns its pytest summary line."""
    rp = os.path.join(ROOT, "tests", "REPORT.txt")
    if not os.path.exists(rp):
        sys.exit("REFUSED: tests/REPORT.txt missing (run run_tests.bat)")
    text = open(rp, encoding="utf-8").read()
    if "golden 12 passed" not in text:
        sys.exit("REFUSED: tests/REPORT.txt does not contain 'golden 12 passed'")
    last = int(_git("log", "-1", "--format=%ct", "--", "app", "data") or 0)
    if os.path.getmtime(rp) < last:
        sys.exit("REFUSED: tests/REPORT.txt is older than the last commit touching app/ or data/ (rerun the tests)")
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    return lines[1] if len(lines) > 1 else lines[0]


def release_text(report_line: str, nfiles: int, payload_bytes: int) -> bytes:
    py = os.path.join(ROOT, "runtime", "python", "python.exe")
    pyv = subprocess.run([py, "-X", "utf8", "--version"], capture_output=True, text=True).stdout.strip() or "unknown"
    ci = subprocess.run([py, "-X", "utf8", os.path.join(ROOT, "scripts", "check_install.py")], cwd=ROOT,
                        capture_output=True, text=True, encoding="utf-8").stdout.strip().splitlines()
    ci_line = next((ln for ln in reversed(ci) if "오류" in ln and "건" in ln), ci[-1] if ci else "no output")
    rows = [("version", VERSION), ("build date", datetime.date.today().isoformat()),
            ("git commit", _git("rev-parse", "HEAD")), ("tests/REPORT.txt", report_line + " / golden 12 passed"),
            ("python runtime", pyv + " (embedded, runtime/python)"), ("check_install", ci_line),
            ("files", "%d (incl. RELEASE.txt and MANIFEST.sha256)" % nfiles),
            ("uncompressed size", "%.1f MB" % (payload_bytes / 1048576))]
    return ("\n".join("%-18s %s" % r for r in rows) + "\n").encode("utf-8")


def preflight(allow_dirty: bool) -> None:
    r = subprocess.run([sys.executable, "-I", os.path.join(ROOT, "scripts", "check_secrets.py")],
                       capture_output=True, text=True, encoding="utf-8")
    if r.stdout.strip() != "OK 0 hits":
        sys.exit("REFUSED: check_secrets did not print 'OK 0 hits': " + r.stdout + r.stderr)
    tracked = _git("ls-files").splitlines()
    bad = env_names(tracked)
    if bad:
        sys.exit("REFUSED: .env file is tracked by git: " + ", ".join(bad))
    for e in find_env_files():
        print("주의: git이 무시하는 비밀 파일이 있습니다(꾸러미에는 넣지 않음): " + e)
    g = subprocess.run(["git", "status", "--porcelain"], cwd=ROOT, capture_output=True, text=True, encoding="utf-8")
    if g.returncode != 0:
        sys.exit("REFUSED: git status failed")
    if g.stdout.strip() and not allow_dirty:
        sys.exit("REFUSED: working tree is not clean (commit first, or --allow-dirty for a rehearsal): " + g.stdout)


def main() -> int:
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--g1", action="store_true", help="intermediate zip (gate G1)")
    g.add_argument("--final", action="store_true", help="11-13 submission zip (gate G2)")
    ap.add_argument("--allow-dirty", action="store_true", help="rehearsal only (--g1): allow uncommitted changes")
    ap.add_argument("--out", default=os.path.join(ROOT, "dist"))
    args = ap.parse_args()
    if args.final and args.allow_dirty:
        sys.exit("REFUSED: --final never builds from a dirty tree")
    if not out_dir_ok(args.out):
        sys.exit("REFUSED: --out must be outside the tree or under dist/")
    rt = [sys.executable, "-X", "utf8", os.path.join(ROOT, "scripts", "build_runtime.py")]
    if args.final:
        print("runtime: running build_runtime.py (idempotent)")
        subprocess.run(rt, cwd=ROOT, check=True)
    elif not os.path.exists(os.path.join(ROOT, "runtime", "python", "python.exe")):
        print("runtime/ missing: building it first")
        subprocess.run(rt, cwd=ROOT, check=True)
    preflight(args.allow_dirty)
    report_line = check_report() if args.final else ""
    files = collect()
    if env_names(files):
        sys.exit("REFUSED: .env file would be packed: " + ", ".join(env_names(files)))
    entries = [(rel, os.path.join(ROOT, *rel.split("/"))) for rel in files]
    os.makedirs(args.out, exist_ok=True)
    extras = []
    if args.final:
        zpath = os.path.join(args.out, FINAL_NAME)
        payload = sum(os.path.getsize(f) for _, f in entries)
        # RELEASE.txt is small and fixed-width in its size fields; its own bytes are not counted
        extras = [("RELEASE.txt", release_text(report_line, len(entries) + 2, payload))]
    else:
        zpath = os.path.join(args.out, "jeju-nongdon-g1-%s.zip" % datetime.date.today().strftime("%Y%m%d"))
    n = write_zip(entries, zpath, extras)
    with zipfile.ZipFile(zpath) as zf:
        leaked = [m for m in zf.namelist() if ".env" in m.lower()]
    if leaked:
        os.remove(zpath)
        sys.exit("REFUSED: .env found in the written zip (deleted): " + ", ".join(leaked))
    if args.final:
        checked = verify_zip(zpath)
        print("verified: %d files match MANIFEST.sha256" % checked)
    mb = os.path.getsize(zpath) / 1048576
    print("zip: %s  files: %d (incl. MANIFEST.sha256)  size: %.1f MB" % (zpath, n, mb))
    if mb > LIMIT_MB:
        sys.exit("ERROR: over %d MB" % LIMIT_MB)
    if mb > WARN_MB:
        print("WARNING: over %d MB" % WARN_MB)
    return 0


if __name__ == "__main__":
    sys.exit(main())
