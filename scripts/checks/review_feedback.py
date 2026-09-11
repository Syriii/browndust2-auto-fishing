"""只读汇总 QTE 证据包；保留原始结果，不从稀疏截图伪造采样统计或命中率。"""

import argparse
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path
from zipfile import BadZipFile, ZipFile

CATEGORIES = {
    "no_observation": ("没有有效观察", "核对截图可用性、观察线程及同轮异常日志"),
    "observation_gap": ("观察断档", "核对实际采样间隔、截图与识别耗时"),
    "feedback_not_detected": ("未识别反馈", "复核原图、遮挡和字形，不直接缩短按键等待"),
    "feedback_not_renewed": ("旧反馈未更新", "核对反馈持续时间及相邻输入"),
    "superseded_by_input": ("下一输入前未确认", "复核相邻输入与去重，不延长归属窗口凑成功"),
    "ambiguous_feedback": ("反馈归属歧义", "核对候选输入和新旧文字，保持未确认"),
    "unattributed_fail": ("FAIL 原因待确认", "保留原图及候选按键，不直接计为按键未命中"),
    "fail_without_input_result": (
        "仅见 FAIL，按键结果未确认",
        "检查机制、到期与后续反馈，不自动补按",
    ),
    "observer_failed": ("观察线程失败", "先处理观察异常，再评估按键效果"),
    "input_records_dropped": ("按键记录丢失", "核对队列溢出和归属不完整标记"),
    "qte_ended": ("本轮结束前未确认", "结合整轮结果和末帧，勿自动补按"),
    "legacy_unclassified": (
        "旧包缺少诊断分类",
        "保留原原因；用后续完整取证补充，不能还原旧采样统计",
    ),
}


def read_bundle(path):
    with path.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    with ZipFile(path) as archive:
        info = archive.getinfo("metadata.json")
        if info.file_size > 2 * 1024 * 1024:
            raise ValueError("metadata.json 超过 2 MiB 上限")
        metadata = json.loads(archive.read(info).decode("utf-8-sig"))
        if not isinstance(metadata, dict):
            raise ValueError("metadata.json 必须是对象")
        names = set(archive.namelist())
    return digest, metadata, names


def feedback_record(metadata, names):
    outcome = metadata["outcome"]
    if not isinstance(outcome, dict):
        raise ValueError("无效的反馈对象")
    diagnostics = outcome.get("diagnostics") or {}
    frames = metadata.get("frames") or []
    if not isinstance(diagnostics, dict):
        raise ValueError("无效的反馈对象或诊断对象")
    if not isinstance(frames, list) or any(not isinstance(frame, dict) for frame in frames):
        raise ValueError("无效的帧列表")
    category = diagnostics.get("category") or "legacy_unclassified"
    if not isinstance(category, str):
        raise ValueError("无效的分类")
    result = outcome.get("result")
    if not isinstance(result, str) or result not in {"unknown", "miss", "hit", "critical"}:
        raise ValueError("无效的反馈结果")
    label, action = CATEGORIES.get(category, ("未识别的诊断分类", "保留原字段并核对对应版本"))
    referenced = [frame.get("file") for frame in frames]
    if any(not isinstance(name, str) for name in referenced):
        raise ValueError("帧文件名必须是文本")
    return dict(
        outcome=outcome,
        category=category,
        category_label=label if result == "unknown" else "已记录游戏反馈",
        next_action=action if result == "unknown" else "复核决策帧及游戏反馈，不推断特殊机制因果",
        saved_frame_count=len(frames),
        missing_frame_files=[name for name in referenced if name not in names],
        decision_frame_available="decision.png" in names,
        has_sampling_diagnostics=bool(diagnostics),
        note="保存帧数不是原始采样数；无关联按键的 FAIL 单列；异常包不代表全部输入样本",
    )


def review(directories):
    files = set()
    for directory in directories:
        if not directory.is_dir():
            raise ValueError(f"输入目录不存在：{directory}")
        files.update(path.resolve() for path in directory.rglob("*.zip"))
    records, errors, copies, contexts = [], [], [], defaultdict(list)
    seen = {}
    for path in sorted(files):
        try:
            digest, metadata, names = read_bundle(path)
            if digest in seen:
                copies.append(dict(path=str(path), original=seen[digest], sha256=digest))
                continue
            round_id = metadata.get("round_id")
            if round_id is not None and not isinstance(round_id, str):
                raise ValueError("无效的 round_id")
            common = dict(path=str(path), sha256=digest, round_id=round_id)
            if "outcome" in metadata:
                if not isinstance(metadata["outcome"], dict):
                    raise ValueError("outcome 必须是对象")
                records.append(dict(common, **feedback_record(metadata, names)))
            else:
                contexts[round_id].append(common)
            seen[digest] = str(path)
        except (OSError, BadZipFile, KeyError, ValueError, RuntimeError) as exc:
            errors.append(dict(path=str(path), error=f"{type(exc).__name__}: {exc}"))
    for record in records:
        record["round_context"] = contexts.get(record["round_id"], []) if record["round_id"] else []
    return dict(
        schema_version=1,
        scanned_archives=len(files),
        unique_feedback_packages=len(records),
        context_packages=sum(map(len, contexts.values())),
        exact_copies=copies,
        errors=errors,
        results=dict(Counter(row["outcome"]["result"] for row in records)),
        unknown_categories=dict(
            Counter(row["category"] for row in records if row["outcome"]["result"] == "unknown")
        ),
        unknown_original_reasons=dict(
            Counter(
                str(row["outcome"].get("reason") or "原包未记录原因")
                for row in records
                if row["outcome"]["result"] == "unknown"
            )
        ),
        unassigned_feedback=sum(row["outcome"].get("attempt") is None for row in records),
        records=records,
        note="只按完整 ZIP 哈希去除副本；相同按键的不同证据仍单列。统计是证据包数量，不是独立故障数或命中率。图片未解码，存在不代表图像完整。",
    )


def markdown(report):
    lines = [
        "# QTE 证据复核索引",
        "",
        f"扫描 {report['scanned_archives']} 包；反馈 {report['unique_feedback_packages']} 包；"
        f"上下文 {report['context_packages']} 包；重复副本 {len(report['exact_copies'])} 包；"
        f"读取错误 {len(report['errors'])} 包。",
        "",
        report["note"],
        "",
        "| 原结果 | 包数量 |",
        "| --- | ---: |",
        *(f"| {key} | {value} |" for key, value in report["results"].items()),
        "",
        "原包未确认原因（保留原文字，不等于根因）：",
        "",
        *(f"- {key}：{value} 包" for key, value in report["unknown_original_reasons"].items()),
        "",
    ]
    for index, row in enumerate(report["records"], 1):
        outcome = row["outcome"]
        lines.extend(
            [
                f"## {index:03d} · {outcome['result']} · {row['category_label']}",
                "",
                f"原包：<{Path(row['path']).as_posix()}>",
                "",
                f"轮次：{row['round_id']}；按键：{outcome.get('attempt')}；原原因：{outcome.get('reason')}",
                "",
                f"保存观察图 {row['saved_frame_count']} 张；决策图：{row['decision_frame_available']}；"
                f"缺失图文件：{row['missing_frame_files']}。",
                "",
                f"建议：{row['next_action']}。",
                "",
            ]
        )
        for context in row["round_context"]:
            lines.extend([f"同轮上下文：<{Path(context['path']).as_posix()}>", ""])
    for error in report["errors"]:
        lines.extend([f"读取失败：{error['path']} — {error['error']}", ""])
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", type=Path, action="append", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    report = review(args.input_dir)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "index.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf8"
    )
    (args.output_dir / "index.md").write_text(markdown(report), encoding="utf8")
    print(
        json.dumps(
            {
                key: value
                for key, value in report.items()
                if key not in {"records", "exact_copies", "errors"}
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    print(f"读取错误：{len(report['errors'])}；重复副本：{len(report['exact_copies'])}")
    return 1 if report["errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
