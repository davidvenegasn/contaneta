"""Tests for deploy scripts and documentation."""

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_predeploy_check_script_exists_and_executable():
    """predeploy_check.sh must exist and be executable."""
    script = ROOT / "scripts" / "predeploy_check.sh"
    assert script.exists(), "scripts/predeploy_check.sh not found"
    assert os.access(script, os.X_OK), "scripts/predeploy_check.sh is not executable"


def test_smoke_prod_script_exists_and_executable():
    """smoke_prod.sh must exist and be executable."""
    script = ROOT / "scripts" / "smoke_prod.sh"
    assert script.exists(), "scripts/smoke_prod.sh not found"
    assert os.access(script, os.X_OK), "scripts/smoke_prod.sh is not executable"


def test_post_deploy_checklist_exists():
    """Post-deploy manual checklist must exist."""
    checklist = ROOT / "scripts" / "post_deploy_manual_checklist.md"
    assert checklist.exists(), "scripts/post_deploy_manual_checklist.md not found"
    content = checklist.read_text()
    # Must contain key sections
    assert "DNS" in content
    assert "HTTPS" in content
    assert "Health" in content
    assert "FIEL" in content
    assert "Sentry" in content
    assert "Backup" in content


def test_deploy_guide_has_all_required_sections():
    """DEPLOY_GUIDE.md must contain all required deployment sections."""
    guide = ROOT / "DEPLOY_GUIDE.md"
    assert guide.exists(), "DEPLOY_GUIDE.md not found"
    content = guide.read_text()
    required = [
        "systemd",
        "Caddy",
        "Pre-Deploy",
        "Post-Deploy",
        "Smoke Test",
        "Cron",
        "backup",
        "Health",
    ]
    for keyword in required:
        assert keyword.lower() in content.lower(), (
            f"DEPLOY_GUIDE.md missing section about '{keyword}'"
        )
