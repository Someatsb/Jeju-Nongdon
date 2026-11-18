"""내장 파이썬 만들기(Task 27): runtime\\python(내장 3.12.10) + runtime\\site-packages(requirements.txt 목록).

센터 PC에 파이썬이 없어도 run.bat이 돈다. 관리자 권한도 필요 없다. 여러 번 돌려도 같은 결과(이미 된 단계는 건너뜀).

1. python-3.12.10-embed-amd64.zip을 runtime\\ 에 받는다(이미 있으면 받지 않음). 받은 파일은 지문을 맞춘 뒤에만 쓴다.
2. runtime\\python\\ 에 푼다.
3. python312._pth 에 ..\\site-packages 와 앱 폴더(..\\..)를 더하고 import site를 켠다.
4. 이 PC의 pip로 requirements.txt를 runtime\\site-packages 에 깐다(--target). get-pip는 필요 없다.

지문: python.org 릴리스 쪽(https://www.python.org/downloads/release/python-31210/)은 이 파일의 MD5만 싣는다.
SHA256은 같은 사이트의 python-3.12.10-embed-amd64.zip.spdx.json 에 적힌 값이다. 둘 다 맞아야 쓴다.
두 값 모두 python.org에서 온 것이라 받는 도중의 손상·불완전한 파일은 막지만, python.org 자체가 뚫린 경우까지 막지는 못한다.
실행: python scripts/build_runtime.py   (인터넷은 이 단계에서만 필요)
"""
import hashlib
import platform
import shutil
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "runtime"
VERSION = "3.12.10"
ZIP_NAME = f"python-{VERSION}-embed-amd64.zip"
URL = f"https://www.python.org/ftp/python/{VERSION}/{ZIP_NAME}"
SHA256 = "4acbed6dd1c744b0376e3b1cf57ce906f9dc9e95e68824584c8099a63025a3c3"   # python.org .spdx.json, 받은 파일과 대조함
MD5 = "fe8ef205f2e9c3ba44d0cf9954e1abd3"                                      # python.org 릴리스 쪽 표
PTH_LINES = ("python312.zip", ".", r"..\site-packages", r"..\..", "", "import site")
MARK = ".complete"      # runtime/ 바로 아래. 스모크 확인까지 통과한 뒤에만 쓴다(중간에 끊긴 설치가 끝난 것처럼 보이지 않게)
SMOKE_MODULES = ("keyring", "pypdf", "anthropic", "fastapi", "uvicorn", "jinja2", "pydantic", "multipart", "httpx", "app.config",
                 "pytest", "bs4", "soupsieve", "pluggy", "iniconfig", "packaging", "pygments", "colorama")   # run_tests.bat needs the test deps


def require_x64() -> None:
    if sys.platform != "win32" or platform.machine().lower() not in ("amd64", "x86_64"):
        raise SystemExit("이 PC는 64비트 Windows(x64)가 아닙니다. 내장 파이썬은 64비트 Windows용만 만듭니다. 중단합니다.")


def say(msg: str) -> None:
    print(msg, flush=True)


def digests(path: Path) -> tuple[str, str]:
    sha, md = hashlib.sha256(), hashlib.md5()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            sha.update(chunk)
            md.update(chunk)
    return sha.hexdigest(), md.hexdigest()


def verified(path: Path) -> bool:
    return digests(path) == (SHA256, MD5)


def fetch_zip(runtime: Path = RUNTIME) -> Path:
    runtime.mkdir(exist_ok=True)
    target = runtime / ZIP_NAME
    if target.exists():
        if verified(target):
            say(f"[1/4] 내장 파이썬 파일이 이미 있습니다(지문 일치): {target.name}")
            return target
        say("[1/4] 받아 둔 파일의 지문이 다릅니다. 지우고 다시 받습니다.")
        target.unlink()
    say(f"[1/4] 내장 파이썬 {VERSION}을 받습니다(약 11MB): {URL}")
    part = target.with_suffix(".part")
    urllib.request.urlretrieve(URL, part)
    if not verified(part):
        part.unlink()
        raise SystemExit("받은 파일의 지문이 python.org 값과 다릅니다. 인터넷 연결을 확인하고 다시 해 보세요. 중단합니다.")
    part.replace(target)
    say("      지문 일치. 저장했습니다.")
    return target


def unpack(zip_path: Path, runtime: Path = RUNTIME) -> Path:
    py_dir = runtime / "python"
    if (py_dir / "python.exe").exists():
        say("[2/4] runtime\\python 이 이미 있습니다. 건너뜁니다.")
        return py_dir
    say("[2/4] runtime\\python 에 풉니다.")
    tmp = runtime / "python.tmp"
    shutil.rmtree(tmp, ignore_errors=True)          # 풀다 끊긴 흔적
    shutil.rmtree(py_dir, ignore_errors=True)       # python.exe 없는 반쪽 폴더
    with zipfile.ZipFile(zip_path) as z:
        z.extractall(tmp)
    tmp.rename(py_dir)                              # 다 풀린 뒤 한 번에 제자리로
    return py_dir


def patch_pth(py_dir: Path) -> None:
    pth = next(py_dir.glob("python*._pth"), None)
    if pth is None:
        raise SystemExit("python312._pth 를 찾지 못했습니다. runtime\\python 을 지우고 다시 하세요.")
    want = "\r\n".join(PTH_LINES) + "\r\n"
    if pth.read_bytes().decode("utf-8") == want:
        say(f"[3/4] {pth.name} 은 이미 맞습니다.")
        return
    pth.write_bytes(want.encode("utf-8"))
    say(f"[3/4] {pth.name} 에 site-packages 와 앱 폴더를 더했습니다.")


def pip_command(site: Path, req_file: Path) -> list[str]:
    return [sys.executable, "-m", "pip", "install", "--target", str(site), "--upgrade",
            "--python-version", "3.12", "--platform", "win_amd64", "--implementation", "cp", "--only-binary=:all:",
            "--no-warn-script-location", "--disable-pip-version-check", "-r", str(req_file)]


def requirements_hash(root: Path = ROOT) -> str:
    return hashlib.sha256((root / "requirements.txt").read_bytes()).hexdigest()


def is_complete(runtime: Path = RUNTIME, root: Path = ROOT) -> bool:
    mark = runtime / MARK
    return mark.exists() and mark.read_text(encoding="ascii").strip() == requirements_hash(root)


def install_requirements(runtime: Path = RUNTIME, root: Path = ROOT) -> None:
    if is_complete(runtime, root):
        say("[4/4] 부품이 이미 설치돼 있습니다(requirements.txt 같음). 건너뜁니다.")
        return
    say("[4/4] 부품을 설치합니다(requirements.txt). 몇 분 걸릴 수 있습니다.")
    (runtime / MARK).unlink(missing_ok=True)
    site = runtime / "site-packages"
    site.mkdir(exist_ok=True)
    # requirements.txt의 한글 주석을 pip(cp949로 읽음)가 못 읽으므로, 부품 줄만 뽑은 영문 파일을 넘긴다.
    req = root / "requirements.txt"
    lines = [ln.strip() for ln in req.read_text(encoding="utf-8").splitlines() if ln.strip() and not ln.strip().startswith("#")]
    plain = runtime / "requirements.plain.txt"
    plain.write_text("\n".join(lines) + "\n", encoding="ascii")
    if subprocess.run(pip_command(site, plain)).returncode != 0:
        raise SystemExit("부품 설치에 실패했습니다. 인터넷 연결과 위 메시지를 확인하세요.")


def smoke(py_dir: Path, root: Path = ROOT) -> None:
    """내장 파이썬이 꼭 필요한 부품을 하나씩 불러와 본다. 하나라도 못 부르면 한국어로 크게 알리고 끝낸다."""
    probe = [
        "import importlib, sys",
        "bad = []",
        "for m in sys.argv[1:]:",
        "    try:",
        "        importlib.import_module(m)",
        "    except Exception as e:",
        "        bad.append(m + ' (' + type(e).__name__ + ')')",
        "print('MISSING:' + '; '.join(bad) if bad else 'ok')",
    ]
    code = chr(10).join(probe)
    r = subprocess.run([str(py_dir / "python.exe"), "-X", "utf8", "-c", code, *SMOKE_MODULES],
                       cwd=root, capture_output=True, text=True, encoding="utf-8", errors="replace")
    out = r.stdout.strip()
    if r.returncode != 0 or out != "ok":
        detail = out if out.startswith("MISSING:") else r.stderr[-800:]
        raise SystemExit("내장 파이썬 확인 실패: 꼭 필요한 부품을 불러오지 못했습니다." + chr(10) + detail + chr(10) +
                         "run.bat이 제대로 안 돌 수 있습니다. runtime 폴더를 지우고 build_runtime.py를 다시 돌려 보세요.")
    say("내장 파이썬 확인: " + ", ".join(SMOKE_MODULES) + " 모두 불러왔습니다.")


def main() -> int:
    require_x64()
    zip_path = fetch_zip()
    py_dir = unpack(zip_path)
    patch_pth(py_dir)
    install_requirements()
    smoke(py_dir)
    (RUNTIME / MARK).write_text(requirements_hash(), encoding="ascii")     # 스모크까지 통과한 뒤에만
    say("끝났습니다. 이제 run.bat 으로 실행하세요(runtime\\python 이 쓰입니다).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
