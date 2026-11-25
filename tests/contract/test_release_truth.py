from __future__ import annotations

import re
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python <3.11
    import tomli as tomllib


def test_version_is_synced_between_pyproject_and_package() -> None:
    pyproject = tomllib.loads(Path("pyproject.toml").read_text())
    package_init = Path("src/roboharness/__init__.py").read_text()
    match = re.search(r'__version__\s*=\s*"([^"]+)"', package_init)
    assert match is not None
    assert pyproject["project"]["version"] == match.group(1)


def test_project_urls_point_to_lowercase_repo() -> None:
    pyproject = tomllib.loads(Path("pyproject.toml").read_text())
    urls = pyproject["project"]["urls"]
    assert "MiaoDX/roboharness" in urls["Homepage"]
    assert "MiaoDX/roboharness" in urls["Repository"]
    assert "MiaoDX/roboharness/issues" in urls["Issues"]
    assert "MiaoDX/roboharness/tree/main/docs" in urls["Documentation"]


def test_citation_metadata_matches_pyproject() -> None:
    """CITATION.cff had drifted from the package: version 0.1.1 and a
    capital-R ``MiaoDX/RobotHarness`` URL that does not exist."""

    pyproject = tomllib.loads(Path("pyproject.toml").read_text())
    citation = Path("CITATION.cff").read_text()

    version_match = re.search(r'^version:\s*"([^"]+)"', citation, flags=re.MULTILINE)
    assert version_match is not None
    assert version_match.group(1) == pyproject["project"]["version"]

    repo_match = re.search(r'^repository-code:\s*"([^"]+)"', citation, flags=re.MULTILINE)
    assert repo_match is not None
    assert "MiaoDX/roboharness" in repo_match.group(1)
    assert "RobotHarness" not in repo_match.group(1)
