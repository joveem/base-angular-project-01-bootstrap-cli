#!/usr/bin/env python3
# delete_buckets.py
# Delete a fixed list of S3 buckets using AWS CLI commands.
# Requirements: AWS CLI v2 installed and configured.

import argparse
import subprocess
import sys
from typing import List

BUCKETS: List[str] = [
    "idk-test-ws-01-development",
    "idk-test-ws-02-development",
    "idk-test-ws-03-beta",
    "idk-test-ws-03-development",
    "idk-test-ws-03-prod",
    "idk-test-ws-05-beta",
    "idk-test-ws-05-development",
    "idk-test-ws-05-prod",
    "idk-test-ws-06-beta",
    "idk-test-ws-06-development",
    "idk-test-ws-06-prod",
    "idk-test-ws-09-beta",
    "idk-test-ws-09-development",
    "idk-test-ws-09-prod",
    "idk-test-ws-11-beta",
    "idk-test-ws-11-development",
    "idk-test-ws-11-prod",
    "idk-test-ws-12-beta",
    "idk-test-ws-12-development",
    "idk-test-ws-12-prod",
    "idk-test-ws-13-beta",
    "idk-test-ws-13-development",
    "idk-test-ws-13-prod",
    "idk-test-ws-14-beta",
    "idk-test-ws-14-development",
    "idk-test-ws-14-prod",
]

def run(cmd: List[str], profile: str = None, check: bool = False):
    env = None
    # Build final command with optional --profile
    final = cmd[:]
    if profile:
        # Insert --profile right after "aws"
        if final and final[0] == "aws":
            final = ["aws", "--profile", profile] + final[1:]
        else:
            final = ["aws", "--profile", profile] + final
    return subprocess.run(final, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=check)

def aws_available() -> bool:
    try:
        out = run(["aws", "--version"])
        return out.returncode == 0
    except Exception:
        return False

def head_bucket(bucket: str, region: str, profile: str = None) -> bool:
    # HEAD Bucket returns 0 if bucket exists and you have permission
    res = run(["aws", "s3api", "head-bucket", "--bucket", bucket, "--region", region], profile=profile)
    return res.returncode == 0

def remove_bucket(bucket: str, region: str, profile: str = None) -> (bool, str):
    # First try the high-level 'rb --force'
    rb = run(["aws", "s3", "rb", f"s3://{bucket}", "--force", "--region", region], profile=profile)
    if rb.returncode == 0:
        return True, rb.stdout.strip()

    # If it failed, attempt plain delete-bucket as a fallback (in case it's truly empty)
    db = run(["aws", "s3api", "delete-bucket", "--bucket", bucket, "--region", region], profile=profile)
    if db.returncode == 0:
        return True, "Deleted by s3api delete-bucket fallback."
    else:
        msg = "rb stderr:\n" + rb.stderr.strip() + "\n\n" + "delete-bucket stderr:\n" + db.stderr.strip()
        return False, msg

def main():
    parser = argparse.ArgumentParser(description="Delete a fixed list of S3 buckets via AWS CLI.")
    parser.add_argument("--profile", help="AWS CLI profile to use", default=None)
    parser.add_argument("--region", help="AWS region to use (for API calls)", default="sa-east-1")
    parser.add_argument("--dry-run", action="store_true", help="Only print actions, do not execute deletions")
    args = parser.parse_args()

    if not aws_available():
        print("ERROR: AWS CLI not found or not available in PATH.", file=sys.stderr)
        sys.exit(2)

    print(f"Region: {args.region} | Profile: {args.profile or 'default'}")
    print(f"Buckets to delete: {len(BUCKETS)}")
    if args.dry_run:
        for b in BUCKETS:
            print(f"[DRY-RUN] Would check and delete bucket: {b}")
        return

    successes = 0
    failures = 0
    for bucket in BUCKETS:
        print(f"---\nProcessing: {bucket}")
        if not head_bucket(bucket, args.region, args.profile):
            print(f"[SKIP] Bucket not found or no access: {bucket}")
            continue

        ok, info = remove_bucket(bucket, args.region, args.profile)
        if ok:
            successes += 1
            print(f"[OK] Deleted: {bucket}")
            if info:
                print(info)
        else:
            failures += 1
            print(f"[FAIL] Could not delete: {bucket}")
            print(info)

    print("\nSummary")
    print(f"  Deleted: {successes}")
    print(f"  Failed : {failures}")
    if failures > 0:
        print("Some buckets failed to delete. If these have versioning enabled, ask for the 'deep-purge' script to remove all versions and delete markers before deletion.")

if __name__ == "__main__":
    main()
