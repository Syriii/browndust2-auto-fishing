"""完整 ZIP 与文件清单协议；用户数据永远不能进入程序替换清单。"""

import hashlib
import json
import re
import shutil
import stat
from pathlib import Path
from zipfile import ZipFile

APP = "BD2_AutoFishing"
EXE = APP + ".exe"
HELPER = "BD2_Updater.exe"
MAX_BYTES = 2 * 1024**3
MAX_FILES = 10000
MANIFEST_LIMIT = 4 * 1024**2


def safe_path(root, relative):
    """拒绝 Windows 别名、ADS、设备名、目录穿越及链接逃逸。"""
    if not isinstance(relative, str) or not relative or "\\" in relative:
        raise ValueError("非法文件路径")
    parts = relative.split("/")
    for part in parts:
        if (
            not part
            or part in {".", ".."}
            or part.endswith((".", " "))
            or any(ord(c) < 32 or c in ':<>"|?*' for c in part)
            or re.fullmatch(r"(?i)(con|prn|aux|nul|com[0-9]|lpt[0-9])", part.split(".")[0])
        ):
            raise ValueError(f"非法文件路径：{relative}")
    root = Path(root).resolve()
    target = root.joinpath(*parts)
    current = root
    for part in parts:
        current = current / part
        if current.is_symlink() or current.is_junction():
            raise ValueError(f"更新路径不能是链接：{relative}")
    if not target.resolve().is_relative_to(root):
        raise ValueError("更新路径超出程序目录")
    return target


def managed(relative):
    return relative in {EXE, HELPER} or relative.startswith("_internal/")


def sha256(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def read_manifest(raw):
    if len(raw) > MANIFEST_LIMIT:
        raise ValueError("文件清单过大")
    manifest = json.loads(raw)
    if manifest.get("schema") != 1 or manifest.get("app") != APP:
        raise ValueError("不是本程序支持的完整更新包")
    if manifest.get("platform") != "windows-x64":
        raise ValueError("更新包平台不匹配，仅支持 Windows x64")
    version = manifest.get("version", "")
    if not re.fullmatch(r"\d+\.\d+\.\d+", version):
        raise ValueError("更新版本必须为三段数字")
    files = manifest.get("files")
    if not isinstance(files, dict) or not 2 <= len(files) <= MAX_FILES:
        raise ValueError("文件清单无效")
    seen = set()
    total = 0
    for name, metadata in files.items():
        safe_path(Path.cwd(), name)
        if not managed(name) or name.casefold() in seen:
            raise ValueError(f"文件清单包含非程序文件或重复路径：{name}")
        seen.add(name.casefold())
        size = metadata.get("size")
        if type(size) is not int or size < 0:
            raise ValueError("文件大小无效")
        if not re.fullmatch(r"[0-9a-f]{64}", metadata.get("sha256", "")):
            raise ValueError("文件校验值无效")
        total += size
    if not {EXE, HELPER}.issubset(files) or total > MAX_BYTES:
        raise ValueError("更新包缺少入口或解压体积超限")
    return manifest


def create_manifest(root, version):
    root = Path(root)
    manifest = dict(schema=1, app=APP, platform="windows-x64", version=version, files={})
    for path in sorted(root.rglob("*")):
        if path.is_file():
            name = path.relative_to(root).as_posix()
            if not managed(name):
                raise ValueError(f"发布目录含非程序文件：{name}")
            manifest["files"][name] = dict(size=path.stat().st_size, sha256=sha256(path))
    raw = json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8")
    read_manifest(raw)
    (root / "manifest.json").write_bytes(raw)
    return manifest


def unpack_verified(archive_path, destination):
    """在独立暂存目录逐文件校验；从不使用 extractall。"""
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=False)
    with ZipFile(archive_path) as archive:
        entries = archive.infolist()
        if len(entries) > MAX_FILES + 1000:
            raise ValueError("压缩包文件过多")
        prefix = APP + "/"
        manifest_name = prefix + "manifest.json"
        info = archive.getinfo(manifest_name)
        if info.file_size > MANIFEST_LIMIT:
            raise ValueError("文件清单过大")
        manifest = read_manifest(archive.read(info))
        seen = set()
        for entry in entries:
            if not entry.filename.startswith(prefix):
                raise ValueError("ZIP 必须包含独立的程序根目录")
            name = entry.filename[len(prefix) :].rstrip("/")
            if not name and entry.is_dir():
                continue
            target = safe_path(destination, name)
            if entry.is_dir():
                continue
            if name.casefold() in seen or stat.S_ISLNK(entry.external_attr >> 16):
                raise ValueError("ZIP 包含重复文件或符号链接")
            seen.add(name.casefold())
            if name == "manifest.json":
                target.write_bytes(archive.read(info))
                continue
            metadata = manifest["files"].get(name)
            if metadata is None or entry.file_size != metadata["size"]:
                raise ValueError(f"ZIP 与文件清单不一致：{name}")
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(entry) as source, target.open("xb") as output:
                shutil.copyfileobj(source, output, 1024 * 1024)
            if sha256(target) != metadata["sha256"]:
                raise ValueError(f"文件损坏，校验失败：{name}")
        if seen != {n.casefold() for n in manifest["files"]} | {"manifest.json"}:
            raise ValueError("ZIP 缺少清单中的文件")
    return manifest


def verify_tree(root, manifest):
    for name, metadata in manifest["files"].items():
        path = safe_path(root, name)
        if (
            not path.is_file()
            or path.stat().st_size != metadata["size"]
            or sha256(path) != metadata["sha256"]
        ):
            raise ValueError(f"程序文件校验失败：{name}")
