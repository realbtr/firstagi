import hashlib
import json
import pytest
from training.h22_report import load_results


def test_report_rejects_modified_raw_artifact_before_analysis(tmp_path):
    artifact = tmp_path / "raw.json"
    artifact.write_bytes(b'{"candidate_sum": 7}')
    expected = hashlib.sha256(artifact.read_bytes()).hexdigest()
    (tmp_path/"SHA256SUMS.json").write_text(json.dumps({"raw.json": expected}))
    (tmp_path/"summary.json").write_text(json.dumps({"complete": True}))
    artifact.write_bytes(b'{"candidate_sum": 999}')
    with pytest.raises(ValueError, match="artifact hash mismatch: raw.json"):
        load_results(tmp_path)


def test_report_rejects_incomplete_suite(tmp_path):
    (tmp_path/"summary.json").write_text(json.dumps({"complete": False}))
    with pytest.raises(ValueError, match="suite is incomplete"):
        load_results(tmp_path)
