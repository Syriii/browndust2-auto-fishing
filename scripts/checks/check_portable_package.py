"""校验候选包，并用实际助手更新隔离的测试 EXE；不运行钓鱼程序。"""

import argparse
import json
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from unittest.mock import patch

from bd2_fishing.infrastructure.updates import package, transaction


def stub_executable(directory):
    source = directory / "Stub.cs"
    source.write_text(
        'using System.IO; class Stub { static void Main() { Directory.CreateDirectory("data"); File.WriteAllText("data/relaunched.txt", "idle"); } }',
        encoding="utf8",
    )
    target = directory / package.EXE
    compiler = Path("C:/Windows/Microsoft.NET/Framework64/v4.0.30319/csc.exe")
    subprocess.run(
        [str(compiler), "/nologo", "/target:winexe", f"/out:{target}", str(source)],
        check=True,
        capture_output=True,
    )
    return target


def wait_for_result(process, root):
    deadline = time.monotonic() + 30
    marker = root / "data/relaunched.txt"
    while time.monotonic() < deadline:
        if marker.exists():
            process.wait(timeout=10)
            assert process.returncode == 0
            return json.loads((root / "cache/updates/result.json").read_text(encoding="utf8"))
        time.sleep(0.1)
    process.kill()
    process.wait(timeout=10)
    raise AssertionError("助手未完成隔离更新，请检查测试目录中的结果")


def exercise_helper(candidate, directory):
    stub = stub_executable(directory)
    root = directory / "installation"
    root.mkdir()
    shutil.copy2(stub, root / package.EXE)
    shutil.copy2(candidate / package.HELPER, root / package.HELPER)
    (root / "_internal").mkdir()
    (root / "_internal/old.dll").write_bytes(b"obsolete")
    package.create_manifest(root, "0.1.0")
    (root / "config").mkdir()
    (root / "config/config.ini").write_bytes(b"personal settings")
    job = root / "cache/updates" / ("b" * 32)
    stage = job / "stage"
    stage.mkdir(parents=True)
    shutil.copy2(stub, stage / package.EXE)
    shutil.copy2(candidate / package.HELPER, stage / package.HELPER)
    (stage / "_internal").mkdir()
    (stage / "_internal/new.dll").write_bytes(b"new dependency")
    package.create_manifest(stage, "0.2.0")
    shutil.copy2(candidate / package.HELPER, job / package.HELPER)
    transaction.write_json(root / "cache/updates/pending.json", dict(job=job.name))
    with transaction.installation_lock(root):
        process = subprocess.Popen(
            [str(job / package.HELPER), "--root", str(root)],
            cwd=root,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        time.sleep(1)
        assert not (root / "cache/updates/result.json").exists(), "助手没有等待主程序退出"
    result = wait_for_result(process, root)
    assert result["ok"], result
    assert not (root / "_internal/old.dll").exists()
    assert (root / "_internal/new.dll").read_bytes() == b"new dependency"
    assert (root / "config/config.ini").read_bytes() == b"personal settings"
    # 模拟在替换过程中进程被终止，随后使用同一个真实 EXE 助手恢复。
    second = root / "cache/updates" / ("c" * 32)
    shutil.copytree(stage, second / "stage")
    shutil.copy2(candidate / package.HELPER, second / package.HELPER)
    original = transaction.replace_file

    def interrupt(source, target):
        if source == second / "stage/_internal/new.dll":
            raise KeyboardInterrupt()
        return original(source, target)

    transaction.write_json(root / "cache/updates/pending.json", dict(job=second.name))
    try:
        with patch.object(transaction, "replace_file", side_effect=interrupt):
            transaction.apply_update(root, second)
    except KeyboardInterrupt:
        pass
    (root / "data/relaunched.txt").unlink()
    process = subprocess.Popen(
        [str(second / package.HELPER), "--root", str(root), "--recover"],
        cwd=root,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    result = wait_for_result(process, root)
    assert result["ok"]
    assert not (root / "cache/updates/pending.json").exists()
    assert (root / "config/config.ini").read_bytes() == b"personal settings"
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("package_dir", type=Path)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    candidate = args.package_dir.resolve()
    manifest = package.read_manifest((candidate / "manifest.json").read_bytes())
    package.verify_tree(candidate, manifest)
    archive = candidate.parent / "BD2_AutoFishing-windows.zip"
    assert package.sha256(archive) == archive.with_suffix(".zip.sha256").read_text().split()[0]
    workspace = Path(__file__).resolve().parents[2]
    base = workspace / ".local/maintenance"
    with tempfile.TemporaryDirectory(prefix="update-exe-check-", dir=base) as temporary:
        directory = Path(temporary)
        unpacked = package.unpack_verified(archive, directory / "unpacked")
        assert unpacked == manifest
        result = exercise_helper(candidate, directory)
    report = dict(
        version=manifest["version"],
        files=len(manifest["files"]),
        zip_sha256=package.sha256(archive),
        exe_sha256=package.sha256(candidate / package.EXE),
        helper_update_and_recovery=result,
        game_started=False,
    )
    transaction.write_json(args.report, report)
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
