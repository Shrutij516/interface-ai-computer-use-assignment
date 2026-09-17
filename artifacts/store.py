"""Read/write artifacts as JSON files under artifacts/capabilities/."""

from pathlib import Path

from artifacts.schema import Artifact

CAPABILITIES_DIR = Path(__file__).parent / "capabilities"


def save_artifact(artifact: Artifact) -> Path:
    CAPABILITIES_DIR.mkdir(parents=True, exist_ok=True)
    path = CAPABILITIES_DIR / f"{artifact.capability_id}__v{artifact.version}.json"
    path.write_text(artifact.model_dump_json(indent=2))
    return path


def load_artifact(capability_id: str, version: str) -> Artifact:
    path = CAPABILITIES_DIR / f"{capability_id}__v{version}.json"
    return Artifact.model_validate_json(path.read_text())
