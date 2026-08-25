"""Compare two audit.json runs and persist a compact regression report."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def _cost(execution: dict[str, Any]) -> float | None:
    if execution.get("cost") is not None:
        return float(execution["cost"])
    values = [call.get("usage_details", {}).get("cost") for call in execution.get("calls", [])]
    return (
        sum(float(value) for value in values if value is not None)
        if any(value is not None for value in values)
        else None
    )


def _reduction(baseline: float | None, candidate: float | None) -> float | None:
    if baseline in {None, 0} or candidate is None:
        return None
    return round((1 - candidate / baseline) * 100, 2)


def compare(baseline_path: Path, candidate_path: Path) -> dict[str, Any]:
    baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
    candidate = json.loads(candidate_path.read_text(encoding="utf-8"))
    baseline_execution = baseline["run"]["model_execution"]
    candidate_execution = candidate["run"]["model_execution"]
    baseline_runs = {item["check_spec_id"]: item for item in baseline["check_runs"]}
    candidate_runs = {item["check_spec_id"]: item for item in candidate["check_runs"]}
    check_comparison = []
    for check_spec_id, before in baseline_runs.items():
        after = candidate_runs.get(check_spec_id)
        check_comparison.append(
            {
                "check_spec_id": check_spec_id,
                "baseline_status": before["status"],
                "candidate_status": after["status"] if after else "missing",
                "status_match": bool(after and before["status"] == after["status"]),
            }
        )
    baseline_findings = {item["check_spec_id"] for item in baseline["issues"]}
    candidate_findings = {item["check_spec_id"] for item in candidate["issues"]}
    baseline_cost = _cost(baseline_execution)
    candidate_cost = _cost(candidate_execution)
    return {
        "baseline": {
            "job_id": baseline["run"]["job_id"],
            "audit_json": str(baseline_path),
            "model_execution": {
                **{
                    key: baseline_execution.get(key)
                    for key in (
                        "call_count",
                        "prompt_tokens",
                        "completion_tokens",
                        "total_tokens",
                        "latency_ms",
                    )
                },
                "cost": baseline_cost,
            },
        },
        "candidate": {
            "job_id": candidate["run"]["job_id"],
            "audit_json": str(candidate_path),
            "model_execution": {
                **{
                    key: candidate_execution.get(key)
                    for key in (
                        "call_count",
                        "prompt_tokens",
                        "completion_tokens",
                        "total_tokens",
                        "latency_ms",
                    )
                },
                "cost": candidate_cost,
            },
        },
        "reduction_percent": {
            "model_calls": _reduction(
                baseline_execution["call_count"], candidate_execution["call_count"]
            ),
            "prompt_tokens": _reduction(
                baseline_execution["prompt_tokens"], candidate_execution["prompt_tokens"]
            ),
            "completion_tokens": _reduction(
                baseline_execution["completion_tokens"],
                candidate_execution["completion_tokens"],
            ),
            "total_tokens": _reduction(
                baseline_execution["total_tokens"], candidate_execution["total_tokens"]
            ),
            "model_latency": _reduction(
                baseline_execution["latency_ms"], candidate_execution["latency_ms"]
            ),
            "cost": _reduction(baseline_cost, candidate_cost),
        },
        "quality": {
            "all_check_statuses_match": all(item["status_match"] for item in check_comparison),
            "baseline_finding_specs": sorted(baseline_findings),
            "candidate_finding_specs": sorted(candidate_findings),
            "finding_specs_match": baseline_findings == candidate_findings,
            "baseline_relative_finding_recall": (
                len(baseline_findings & candidate_findings) / len(baseline_findings)
                if baseline_findings
                else 1.0
            ),
            "candidate_findings_all_located": all(
                item["location_status"] == "located" for item in candidate["issues"]
            ),
        },
        "checks": check_comparison,
    }


def _markdown(comparison: dict[str, Any]) -> str:
    before = comparison["baseline"]["model_execution"]
    after = comparison["candidate"]["model_execution"]
    reduction = comparison["reduction_percent"]
    quality = comparison["quality"]
    rows = "\n".join(
        f"| {item['check_spec_id']} | {item['baseline_status']} | "
        f"{item['candidate_status']} | {'一致' if item['status_match'] else '不一致'} |"
        for item in comparison["checks"]
    )
    return f"""# 7 次版与 2 次版对比

| 指标 | 7 次版 | 2 次版 | 降幅 |
|---|---:|---:|---:|
| 模型调用 | {before["call_count"]} | {after["call_count"]} | {reduction["model_calls"]}% |
| 输入 Token | {before["prompt_tokens"]} | {after["prompt_tokens"]} | {reduction["prompt_tokens"]}% |
| 输出 Token | {before["completion_tokens"]} | {after["completion_tokens"]} | {reduction["completion_tokens"]}% |
| 总 Token | {before["total_tokens"]} | {after["total_tokens"]} | {reduction["total_tokens"]}% |
| 模型成本 | {before["cost"]} | {after["cost"]} | {reduction["cost"]}% |

质量结果：全部 CheckSpec 状态一致 = {quality["all_check_statuses_match"]}；问题类型一致 = {quality["finding_specs_match"]}；相对问题召回率 = {quality["baseline_relative_finding_recall"]:.0%}；候选问题全部可定位 = {quality["candidate_findings_all_located"]}。

| CheckSpec | 7 次版 | 2 次版 | 对比 |
|---|---|---|---|
{rows}
"""


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("baseline", type=Path)
    parser.add_argument("candidate", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    comparison = compare(args.baseline, args.candidate)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "comparison-7-vs-2.json").write_text(
        json.dumps(comparison, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (args.output_dir / "comparison-7-vs-2.md").write_text(_markdown(comparison), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
