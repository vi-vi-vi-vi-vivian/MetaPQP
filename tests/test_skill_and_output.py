import json
from pathlib import Path

from portal_audit.domain.models import (
    ElementLocation,
    Finding,
    ModelCallRecord,
    Severity,
    StandardReference,
    StandardRelation,
)
from portal_audit.domain.registry import StandardsRegistry
from portal_audit.interfaces.reporting.output_writer import OutputWriter
from portal_audit.skill_runtime.loader import SkillLoader

from .factories import make_result

ROOT = Path(__file__).parents[1]


def test_skill_loader_reads_model_invoked_skill_package():
    skill = SkillLoader(ROOT / "skills").load("product-value")

    assert skill.name == "product-value"
    assert skill.version == "1.0.0"
    assert "Produce one result" in skill.instructions
    assert skill.path.name == "SKILL.md"


def test_output_writer_preserves_page_first_compatibility_contract(tmp_path):
    result = make_result(job_id="audit-output", artifact_root=tmp_path)
    writer = OutputWriter(tmp_path, model_name="test-model", model_enabled=False)

    run_dir = writer.write(result)
    payload = json.loads((run_dir / "audit.json").read_text(encoding="utf-8"))

    assert run_dir == tmp_path / "web" / "demo" / "page-demo" / "desktop" / "zh-CN" / "audit-output"
    assert (run_dir / "report.html").is_file()
    assert (run_dir / "checkplan.json").is_file()
    assert payload["schema_version"] == "2.3"
    assert payload["sections"][0]["id"] == "page-demo"
    assert payload["pages"][0]["target"]["page_id"] == "page-demo"
    assert payload["page_assessments"][0]["page_id"] == "page-demo"
    assert payload["sections"][0]["screenshot"] == "screenshots/page.png"
    assert "stage_analysis" not in payload
    assert "cross_stage_checks" not in payload
    assert "issues" not in payload["sections"][0]
    assert "check_runs" not in payload["page_assessments"][0]
    assert "context" not in payload["page_assessments"][0]
    assert "body_text" not in payload["pages"][0]["snapshot"]
    assert "evidence_elements" not in payload["pages"][0]["snapshot"]
    assert "evidence_summary" in payload["pages"][0]["snapshot"]


def test_output_writer_records_real_model_usage_without_duplication(tmp_path):
    result = make_result(job_id="20260824-120000")
    result.model_calls.append(
        ModelCallRecord(
            batch_id="single:copy-quality",
            check_spec_ids=["copy-quality"],
            model="test-model",
            prompt_tokens=1200,
            completion_tokens=80,
            total_tokens=1280,
            latency_ms=350,
            usage_details={"cost": 0.0125},
        )
    )
    writer = OutputWriter(tmp_path, model_name="test-model", model_enabled=True)

    run_dir = writer.write(result)
    payload = json.loads((run_dir / "audit.json").read_text(encoding="utf-8"))

    execution = payload["run"]["model_execution"]
    assert execution["call_count"] == 1
    assert execution["prompt_tokens"] == 1200
    assert execution["completion_tokens"] == 80
    assert execution["total_tokens"] == 1280
    assert execution["cost"] == 0.0125
    assert execution["calls"][0]["check_spec_ids"] == ["copy-quality"]


def test_output_writer_emits_json_locations_and_annotated_evidence_map(tmp_path):
    result = make_result(job_id="audit-located", artifact_root=tmp_path)
    result.snapshot.document_size = {"width": 1440, "height": 2400}
    result.assessment.findings.append(
        Finding(
            page_id=result.target.page_id,
            snapshot_id=result.snapshot.snapshot_id,
            check_run_id="checkrun-copy",
            check_spec_id="copy-quality",
            check_spec_version="1.0.0",
            title="页面存在重复词",
            severity=Severity.P2,
            confidence=0.98,
            evidence="购买后后不支持退订",
            standard_refs=[
                StandardReference(
                    criterion_id="metapqp-internal/copy-quality",
                    relation=StandardRelation.IMPLEMENTS,
                )
            ],
            locations=[
                ElementLocation(
                    element_ref="dom-12",
                    selector="#terms",
                    tag="p",
                    text="购买后后不支持退订",
                    bounds={"x": 120, "y": 800, "width": 320, "height": 32},
                )
            ],
        )
    )
    standards = StandardsRegistry(ROOT / "config" / "standards").load()
    writer = OutputWriter(
        tmp_path,
        model_name="test-model",
        model_enabled=True,
        standards=standards,
    )

    run_dir = writer.write(result)
    payload = json.loads((run_dir / "audit.json").read_text(encoding="utf-8"))
    report = (run_dir / "report.html").read_text(encoding="utf-8")

    issue = payload["issues"][0]
    assert issue["location_status"] == "located"
    assert issue["locations"][0]["element_ref"] == "dom-12"
    assert issue["annotated_screenshot"] == "screenshots/page-annotated.svg"
    assert issue["standard_refs"][0]["source_type"] == "internal_guidance"
    assert payload["standards"]["sources"][0]["source_id"] == "metapqp-internal"
    assert (run_dir / issue["annotated_screenshot"]).is_file()
    assert "问题证据地图" in report
    assert "在截图中查看定位框" in report
