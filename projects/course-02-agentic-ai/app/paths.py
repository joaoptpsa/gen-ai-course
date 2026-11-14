"""Where the workbench finds cases, checks, harnesses, results and requirements."""

from __future__ import annotations

from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = PROJECT_DIR.parents[1]

CASES_DIR = PROJECT_DIR / "cases"
CHECKS_DIR = PROJECT_DIR / "checks"
HARNESSES_DIR = PROJECT_DIR / "harnesses"
RESULTS_DIR = PROJECT_DIR / "results"
REQUIREMENTS_FILE = PROJECT_DIR / "requirements.yaml"
GUI_HOME = PROJECT_DIR / "app" / "gui" / "Home.py"

# Session harnesses are offered as read-only baselines.
SESSIONS_DIR = REPO_ROOT / "sessions" / "course-02-agentic-ai"
