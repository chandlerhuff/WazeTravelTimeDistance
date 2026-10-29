"""Validate the release metadata against the installed upstream baseline."""

from importlib import metadata, resources
import json
from pathlib import Path


def test_release_and_shared_dependency_alignment():
    """The explicit shared pin must match built-in Waze and the tested library."""
    root = Path(__file__).resolve().parents[1]
    custom = json.loads(
        (root / "custom_components/waze_travel_time_distance/manifest.json").read_text()
    )
    upstream = json.loads(
        resources.files("homeassistant.components.waze_travel_time")
        .joinpath("manifest.json")
        .read_text()
    )
    assert custom["version"] == "0.9.0"
    assert custom["domain"] == "waze_travel_time_distance"
    assert custom["requirements"] == upstream["requirements"] == ["pywaze==1.2.4"]
    assert metadata.version("pywaze") == "1.2.4"
    assert metadata.version("homeassistant") == "2026.10.4"
    assert json.loads((root / "hacs.json").read_text())["homeassistant"] == "2026.10.4"
