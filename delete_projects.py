#!/usr/bin/env python3
import subprocess
import sys

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


def delete_project(project_id: str) -> bool:
    print(f"\nDeleting {project_id}...")
    result = subprocess.run(
        ["gcloud", "projects", "delete", project_id, "--quiet"],
        capture_output=True,
        text=True,
    )
    if result.returncode == 0:
        print(f"  ✔ Deleted {project_id}")
        return True
    print(f"  ✖ Failed to delete {project_id}: {result.stderr or result.stdout or 'unknown error'}")
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
