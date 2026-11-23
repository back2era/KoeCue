"""Build and verify the portable Windows x64 release."""
import argparse
from hashlib import file_digest
import importlib.metadata as metadata
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import sysconfig
import tempfile

from ai_japanese_interview_assistant import APP_NAME, APP_VERSION


ROOT = Path(__file__).resolve().parents[1]


def sha256(path):
    with path.open("rb") as data:
        return file_digest(data, "sha256").hexdigest()


def make_icon(path):
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    from PySide6.QtWidgets import QApplication
    from ai_japanese_interview_assistant.glass import application_icon

    app = QApplication([])
    if not application_icon().pixmap(256, 256).save(str(path), "ICO"):
        raise SystemExit("Could not create the KoeCue Windows icon.")
    app.quit()


def version_resource(path):
    version = tuple(int(part) for part in APP_VERSION.split(".")) + (0,)
    path.write_text(
        f"""VSVersionInfo(
  ffi=FixedFileInfo(filevers={version}, prodvers={version}, mask=0x3f, flags=0x0,
    OS=0x40004, fileType=0x1, subtype=0x0, date=(0, 0)),
  kids=[StringFileInfo([StringTable('040904B0', [
    StringStruct('FileDescription', '{APP_NAME}'),
    StringStruct('FileVersion', '{APP_VERSION}'),
    StringStruct('InternalName', '{APP_NAME}'),
    StringStruct('OriginalFilename', '{APP_NAME}.exe'),
    StringStruct('ProductName', '{APP_NAME}'),
    StringStruct('ProductVersion', '{APP_VERSION}'),
    StringStruct('LegalCopyright', 'Copyright (c) 2026 back2era')
  ])]), VarFileInfo([VarStruct('Translation', [1033, 1200])])])
""",
        encoding="utf-8",
    )


def copy_notices(release):
    notices = release / "licenses"
    shutil.copytree(ROOT / "licenses", notices, ignore=shutil.ignore_patterns("Whisper-MIT.txt"))
    shutil.copy2(Path(sys.base_prefix) / "LICENSE.txt", notices / "Python-LICENSE.txt")
    for line in (ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines():
        name, pinned, _ = line.partition("==")
        if not pinned:
            continue
        distribution = metadata.distribution(name)
        for file in distribution.files or ():
            if (".." in file.parts or not re.match(r"(?i)(licen[cs]e|copying|notice|thirdparty)", file.name)
                    or file.suffix.lower() not in {"", ".txt", ".md", ".rst"}
                    or file.name == "LicenseRef-Qt-Commercial.txt"):
                continue
            target = notices / name / file
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(distribution.locate_file(file), target)


def windows_system_path():
    windows = Path(os.environ.get("SystemRoot", r"C:\Windows"))
    return os.pathsep.join((str(windows / "System32"), str(windows)))


def verify(release, work):
    report = work / "package-check.json"
    env = dict(os.environ)
    env.pop("PYTHONPATH", None)
    env.pop("PYTHONHOME", None)
    env.pop("QT_PLUGIN_PATH", None)
    env.pop("QT_QPA_PLATFORM_PLUGIN_PATH", None)
    env["PATH"] = windows_system_path()
    env["LOCALAPPDATA"] = str(work / "fresh-local-appdata")
    env["QT_QPA_PLATFORM"] = "windows"
    startup = subprocess.STARTUPINFO()
    startup.dwFlags = subprocess.STARTF_USESHOWWINDOW
    startup.wShowWindow = subprocess.SW_HIDE
    result = subprocess.run(
        [str(release / f"{APP_NAME}.exe"), "--verify-installation", str(report)],
        cwd=work, env=env, startupinfo=startup, timeout=120, check=False,
    )
    if not report.is_file():
        raise SystemExit(f"The executable did not produce a package check (exit {result.returncode}).")
    checks = json.loads(report.read_text(encoding="utf-8"))
    if (result.returncode != 0 or checks.get("version") != APP_VERSION
            or checks.get("bundled_whisper") is not False or checks.get("qt_platform") != "windows"
            or checks.get("main_window_tabs") != 4 or checks.get("local_sherpa") is not True
            or checks.get("speech_models") != [
                "sensevoice-int8", "sensevoice-fp32", "qwen3-asr-0.6b", "qwen3-asr-1.7b",
                "qwen-3.1", "qwen-3.0", "openai", "doubao", "deepseek",
            ]):
        raise SystemExit(f"Packaged application failed its check:\n{json.dumps(checks, ensure_ascii=False, indent=2)}")
    print(f"Package check: {json.dumps(checks, ensure_ascii=False)}")


def main():
    if sys.platform != "win32" or sys.version_info[:2] != (3, 13) or sysconfig.get_platform() != "win-amd64":
        raise SystemExit("Build with Windows x64 Python 3.13.")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "dist",
                        help="Directory for the verified ZIP (default: dist).")
    args = parser.parse_args()

    build_root = ROOT / "build"
    build_root.mkdir(exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix="windows-", dir=build_root))
    print(f"Build workspace: {work}", flush=True)
    icon = work / "koecue.ico"
    version = work / "version.txt"
    make_icon(icon)
    version_resource(version)
    # Native extensions use their wheel's DLLs and Windows system libraries.
    # A developer's PATH may contain an incompatible DLL with the same name.
    env = dict(os.environ, PATH=windows_system_path(), PYINSTALLER_CONFIG_DIR=str(work / "pyinstaller-cache"))
    subprocess.run([
        sys.executable, "-m", "PyInstaller", "--name", APP_NAME, "--onedir", "--windowed", "--noupx",
        "--icon", str(icon), "--version-file", str(version),
        "--distpath", str(work / "release"), "--workpath", str(work / "objects"), "--specpath", str(work),
        "--exclude-module", "pytest", "--exclude-module", "av", "--exclude-module", "faster_whisper",
        "--exclude-module", "ctranslate2", "--exclude-module", "onnxruntime",
        "--exclude-module", "huggingface_hub", "--exclude-module", "tokenizers",
        "--collect-binaries", "sherpa_onnx", "--copy-metadata", "keyring", str(ROOT / "launch.pyw"),
    ], cwd=ROOT, env=env, check=True)
    release = work / "release" / APP_NAME
    if (release / "models").exists() or any(release.rglob("model.bin")) or any(release.rglob("*.onnx")):
        raise SystemExit("The release unexpectedly contains bundled model weights.")
    for name in ("README.md", "LICENSE", "THIRD_PARTY_NOTICES.md"):
        shutil.copy2(ROOT / name, release / name)
    shutil.copytree(ROOT / "docs" / "images", release / "docs" / "images")
    for name in ("scripts/build_windows.py", "docs/superpowers/plans/2026-11-10-koecue.md"):
        target = release / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / name, target)
    copy_notices(release)
    verify(release, work)

    archive_name = f"{APP_NAME}-{APP_VERSION}"
    archive = Path(shutil.make_archive(str(work / archive_name), "zip", release.parent, APP_NAME))
    output = args.output_dir.resolve()
    output.mkdir(exist_ok=True)
    final = output / archive.name
    archive.replace(final)
    print(f"{final} ({final.stat().st_size:,} bytes)\nSHA-256 {sha256(final)}")


if __name__ == "__main__":
    main()
