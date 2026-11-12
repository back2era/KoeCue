"""Build and verify the portable Windows x64 release."""
import argparse
from hashlib import file_digest
import importlib.metadata as metadata
import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys
import tempfile

from ai_japanese_interview_assistant import APP_NAME, APP_VERSION
from ai_japanese_interview_assistant.local_asr import MODEL_FILES, MODEL_REVISION, model_directory


ROOT = Path(__file__).resolve().parents[1]
MODEL_SHA256 = {
    "config.json": "56a6d8110d311f19c8f0471e562832c7527f146b567275bfca59fcf7c184da9a",
    "model.bin": "d01c3014881c9c6f3133c182f3d2887eb6ca1c789a7538c5c007196857a0a6a9",
    "tokenizer.json": "fb7b63191e9bb045082c79fd742a3106a12c99513ab30df4a0d47fa6cb6fd0ab",
    "vocabulary.txt": "34ce3fe1c5041027b3f8d42912270993f986dbc4bb34cf27f951e34a1e453913",
}


def sha256(path):
    with path.open("rb") as data:
        return file_digest(data, "sha256").hexdigest()


def validate_model(source):
    for name in MODEL_FILES:
        path = source / name
        if not path.is_file() or sha256(path) != MODEL_SHA256[name]:
            raise SystemExit(f"Missing or invalid model file: {path}\nExpected Whisper revision {MODEL_REVISION}.")


def prepare_faster_whisper(build):
    distribution = metadata.distribution("faster-whisper")
    if distribution.version != "1.2.1":
        raise SystemExit("The release patch requires faster-whisper 1.2.1.")
    patched = build / "patched"
    target = patched / "faster_whisper"
    shutil.copytree(distribution.locate_file("faster_whisper"), target, ignore=shutil.ignore_patterns("__pycache__"))
    audio = target / "audio.py"
    source = audio.read_text(encoding="utf-8")
    import_block = "import av\nimport numpy as np"
    decoder_start = "    resampler = av.audio.resampler.AudioResampler("
    if source.count(import_block) != 1 or source.count(decoder_start) != 1:
        raise SystemExit("The faster-whisper audio source has changed. Review the release patch.")
    # KoeCue sends float PCM arrays to WhisperModel. File decoding is outside this executable.
    source = source.replace(import_block, "import numpy as np\n\ntry:\n    import av\nexcept ImportError:\n    av = None")
    source = source.replace(decoder_start, "    if av is None:\n"
                            "        raise RuntimeError('The KoeCue release accepts decoded PCM arrays only.')\n\n"
                            + decoder_start)
    audio.write_text(source, encoding="utf-8")
    return patched


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
    shutil.copytree(ROOT / "licenses", notices)
    shutil.copy2(Path(sys.base_prefix) / "LICENSE.txt", notices / "Python-LICENSE.txt")
    for requirements in ("requirements.txt", "requirements-local.txt"):
        for line in (ROOT / requirements).read_text(encoding="utf-8").splitlines():
            name, pinned, _ = line.partition("==")
            if not pinned or name == "av":
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
    if (result.returncode != 0 or checks.get("version") != APP_VERSION or not checks.get("bundled_model")
            or not checks.get("local_inference") or checks.get("qt_platform") != "windows"
            or checks.get("main_window_tabs") != 3):
        raise SystemExit(f"Packaged application failed its check:\n{json.dumps(checks, ensure_ascii=False, indent=2)}")
    print(f"Package check: {json.dumps(checks, ensure_ascii=False)}")


def main():
    if sys.platform != "win32" or sys.version_info[:2] != (3, 13) or platform.machine().lower() not in {"amd64", "x86_64"}:
        raise SystemExit("Build with Windows x64 Python 3.13.")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-dir", type=Path, default=model_directory(),
                        help="Directory containing the four pinned Whisper model files.")
    args = parser.parse_args()
    source = args.model_dir.resolve()
    validate_model(source)

    build_root = ROOT / "build"
    build_root.mkdir(exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix="windows-", dir=build_root))
    print(f"Build workspace: {work}", flush=True)
    patched = prepare_faster_whisper(work)
    icon = work / "koecue.ico"
    version = work / "version.txt"
    make_icon(icon)
    version_resource(version)
    # Native extensions use their wheel's DLLs and Windows system libraries.
    # A developer's PATH may contain an incompatible DLL with the same name.
    env = dict(os.environ, PATH=windows_system_path(), PYINSTALLER_CONFIG_DIR=str(work / "pyinstaller-cache"))
    subprocess.run([
        sys.executable, "-m", "PyInstaller", "--name", APP_NAME, "--onedir", "--windowed", "--noupx",
        "--icon", str(icon), "--version-file", str(version), "--paths", str(patched),
        "--distpath", str(work / "release"), "--workpath", str(work / "objects"), "--specpath", str(work),
        "--exclude-module", "av", "--exclude-module", "pytest",
        "--collect-data", "faster_whisper", "--collect-binaries", "ctranslate2",
        "--copy-metadata", "keyring", str(ROOT / "launch.pyw"),
    ], cwd=ROOT, env=env, check=True)
    release = work / "release" / APP_NAME
    if any(path.name.lower().startswith(("avcodec-", "avformat-", "libx264-", "libx265-"))
           for path in release.rglob("*.dll")):
        raise SystemExit("The release unexpectedly contains multimedia libraries from the PyAV wheel.")
    model = release / "models" / "faster-whisper-base"
    model.mkdir(parents=True)
    for name in MODEL_FILES:
        shutil.copy2(source / name, model / name)
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
    output = ROOT / "dist"
    output.mkdir(exist_ok=True)
    final = output / archive.name
    archive.replace(final)
    print(f"{final} ({final.stat().st_size:,} bytes)\nSHA-256 {sha256(final)}")


if __name__ == "__main__":
    main()
