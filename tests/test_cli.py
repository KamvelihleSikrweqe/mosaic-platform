import json

from mosaic_cli import validate_manifest


def test_cli_validates_manifest_v1_and_component_allowlist():
    valid = {
        "schemaVersion": "1.0",
        "pages": [{
            "name": "Overview", "type": "dashboard",
            "components": [{"type": "heading", "props": {"text": "Suppliers"}}],
        }],
    }
    assert validate_manifest(valid) == []
    invalid = {
        "schemaVersion": "2.0",
        "pages": [{
            "type": "dashboard",
            "components": [{"type": "arbitrary-code", "props": {"source": "bad"}}],
        }],
    }
    assert len(validate_manifest(invalid)) >= 2
