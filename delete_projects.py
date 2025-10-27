#!/usr/bin/env python3
import shutil
import subprocess
import sys
from pathlib import Path

PROJECT_IDS = [
    "idk-test-ws-03",
    "idk-test-ws-05",
    "idk-test-ws-06",
    "idk-test-ws-09",
    "idk-test-ws-11",
    "idk-test-ws-12",
    "idk-test-ws-13",
    "idk-test-ws-14",
    "idk-test-ws-15",
    "test-01-19518",
    "test-01-92ba6",
    "teste001-263ac",
]


def resolve_gcloud_executable() -> str:
    """Return the first usable gcloud executable or exit with instructions."""
    candidates = [
        "gcloud",
        "gcloud.cmd",
        "gcloud.exe",
        str(Path.home() / "AppData/Local/Google/Cloud SDK/google-cloud-sdk/bin/gcloud.CMD"),
    ]
    for candidate in candidates:
        resolved = shutil.which(candidate)
        if resolved:
            return resolved
    print("gcloud CLI not found. Install Google Cloud SDK or add it to PATH.")
    sys.exit(2)


GCLOUD = resolve_gcloud_executable()


def delete_project(project_id: str) -> bool:
    print(f"\nDeleting {project_id}...")
    result = subprocess.run(
        [GCLOUD, "projects", "delete", project_id, "--quiet"],
        capture_output=True,
        text=True,
    )
    if result.returncode == 0:
        print(f"  OK Deleted {project_id}")
        return True
    print(f"  !! Failed to delete {project_id}: {result.stderr or result.stdout or 'unknown error'}")
    return False


def main() -> int:
    failures = 0
    for project_id in PROJECT_IDS:
        if not delete_project(project_id):
            failures += 1
    print(
        f"\nFinished: {len(PROJECT_IDS) - failures} deleted, {failures} failed."
        "\nRemember you can undo within 30 days using `gcloud projects undelete <project-id>`."
    )
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
