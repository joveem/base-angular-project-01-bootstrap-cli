#!/usr/bin/env python3
"""
Project bootstrap CLI to automate onboarding of new Angular + Tailwind projects
with optional Three.js, Node.js API, Firestore, and AWS S3 integrations.

The script guides you through:
1. Selecting the desired stack composition.
2. Validating required tooling.
3. Cloning the template repository and renaming it.
4. Creating Firebase projects, hosting sites, Firestore (optional), AWS buckets (optional).
5. Performing search & replace of project placeholders.
6. Duplicating build folders and updating Firebase config files.
7. Summarising remaining manual steps (e.g., Render.com API setup, DNS updates).

The goal is to automate as much of the 13-step workflow as practicable while
surfacing clear guidance when manual intervention remains necessary.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import textwrap
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Set, Tuple

TEMPLATE_REPO_URL = "https://github.com/joveem/base-angular-project-01.git"
DEFAULT_TEMPLATE_DIRNAME = "base-angular-project-01"
DEFAULT_PLACEHOLDER_INTERNAL = "base-angular-project-01"
DEFAULT_PLACEHOLDER_INTERNAL_CAMEL = "BaseAngularProjects01"
DEFAULT_PLACEHOLDER_PUBLIC = "BaseAngularProjects01"
DEFAULT_PLACEHOLDER_PUBLIC_NAME = "Base Angular Projects 01"
AWS_REGION = "sa-east-1"
FIREBASE_HOSTING_IP = "199.36.158.100"
FIREBASE_CNAME = "ghs.googlehosted.com"
ENVIRONMENTS = ["local", "development", "beta", "prod"]
RENDER_DEFAULT_PLAN = "starter"

remaining_tasks: List[str] = []


class BootstrapError(RuntimeError):
    """Custom error for bootstrap failures."""


@dataclass(frozen=True)
class StackOption:
    key: str
    label: str
    features: Set[str]


STACK_OPTIONS: Sequence[StackOption] = [
    StackOption(
        "angular_tailwind_threejs_node_aws_firestore",
        "angular + tailtwindcss + threejs + nodejs-api + aws s3 bucket + firestore",
        {"threejs", "node_api", "aws_s3", "firestore"},
    ),
    StackOption(
        "angular_tailwind_threejs_node_firestore",
        "angular + tailtwindcss + threejs + nodejs-api + firestore",
        {"threejs", "node_api", "firestore"},
    ),
    StackOption(
        "angular_tailwind_threejs_node_aws",
        "angular + tailtwindcss + threejs + nodejs-api + aws s3 bucket",
        {"threejs", "node_api", "aws_s3"},
    ),
    StackOption(
        "angular_tailwind_threejs_node",
        "angular + tailtwindcss + threejs + nodejs-api",
        {"threejs", "node_api"},
    ),
    StackOption(
        "angular_tailwind_threejs_aws_firestore",
        "angular + tailtwindcss + threejs + aws s3 bucket + firestore",
        {"threejs", "aws_s3", "firestore"},
    ),
    StackOption(
        "angular_tailwind_threejs_firestore",
        "angular + tailtwindcss + threejs + firestore",
        {"threejs", "firestore"},
    ),
    StackOption(
        "angular_tailwind_threejs_aws",
        "angular + tailtwindcss + threejs + aws s3 bucket",
        {"threejs", "aws_s3"},
    ),
    StackOption(
        "angular_tailwind_threejs",
        "angular + tailtwindcss + threejs",
        {"threejs"},
    ),
    StackOption(
        "angular_tailwind_node_aws_firestore",
        "angular + tailtwindcss + nodejs-api + aws s3 bucket + firestore",
        {"node_api", "aws_s3", "firestore"},
    ),
    StackOption(
        "angular_tailwind_node_firestore",
        "angular + tailtwindcss + nodejs-api + firestore",
        {"node_api", "firestore"},
    ),
    StackOption(
        "angular_tailwind_node_aws",
        "angular + tailtwindcss + nodejs-api + aws s3 bucket",
        {"node_api", "aws_s3"},
    ),
    StackOption(
        "angular_tailwind_node",
        "angular + tailtwindcss + nodejs-api",
        {"node_api"},
    ),
    StackOption(
        "angular_tailwind_aws_firestore",
        "angular + tailtwindcss + aws s3 bucket + firestore",
        {"aws_s3", "firestore"},
    ),
    StackOption(
        "angular_tailwind_firestore",
        "angular + tailtwindcss + firestore",
        {"firestore"},
    ),
    StackOption(
        "angular_tailwind_aws",
        "angular + tailtwindcss + aws s3 bucket",
        {"aws_s3"},
    ),
    StackOption(
        "angular_tailwind",
        "angular + tailtwindcss",
        set(),
    ),
]

REQUIRED_COMMANDS_BASE: Dict[str, Tuple[str, str]] = {
    "git": ("Install Git", "https://git-scm.com/downloads"),
    "node": ("Install Node.js (>=18.x)", "https://nodejs.org/en/download/"),
    "npm": ("Install npm (bundled with Node.js)", "https://nodejs.org/en/download/"),
    "ng": ("Install Angular CLI", "npm install -g @angular/cli"),
}

OPTIONAL_COMMANDS: Dict[str, Tuple[str, str]] = {
    "firebase": ("Install Firebase CLI", "npm install -g firebase-tools"),
    "gcloud": ("Install Google Cloud SDK (for Firestore Admin)", "https://cloud.google.com/sdk/docs/install"),
    "aws": ("Install AWS CLI v2", "https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html"),
    "render": ("Install Render CLI", "npm install -g render-cli"),
}


def run_command(command: Sequence[str], cwd: Optional[Path] = None, check: bool = True) -> subprocess.CompletedProcess:
    """Run a subprocess command with echoing."""
    print(f"\n$ {' '.join(command)}")
    result = subprocess.run(command, cwd=cwd, text=True, capture_output=True)
    if check and result.returncode != 0:
        print(result.stdout)
        print(result.stderr, file=sys.stderr)
        raise BootstrapError(f"Command failed: {' '.join(command)}")
    if result.stdout:
        print(result.stdout)
    if result.stderr:
        print(result.stderr, file=sys.stderr)
    return result


def ensure_command_available(command: str) -> bool:
    return shutil.which(command) is not None


def validate_prerequisites(features: Set[str]) -> bool:
    missing: List[Tuple[str, Tuple[str, str]]] = []
    for cmd, info in REQUIRED_COMMANDS_BASE.items():
        if not ensure_command_available(cmd):
            missing.append((cmd, info))

    need_firebase = "firestore" in features or features.intersection({"threejs", "aws_s3", "node_api"})
    need_aws = "aws_s3" in features
    need_render = "node_api" in features

    if need_firebase and not ensure_command_available("firebase"):
        missing.append(("firebase", OPTIONAL_COMMANDS["firebase"]))
    if "firestore" in features and not ensure_command_available("gcloud"):
        missing.append(("gcloud", OPTIONAL_COMMANDS["gcloud"]))
    if need_aws and not ensure_command_available("aws"):
        missing.append(("aws", OPTIONAL_COMMANDS["aws"]))
    if need_render and not ensure_command_available("render"):
        missing.append(("render", OPTIONAL_COMMANDS["render"]))

    if missing:
        print("\nRequired tooling missing. Please install the following before continuing:\n")
        for cmd, (hint, link) in missing:
            print(f" - {cmd}: {hint}")
            if link:
                print(f"   {link}")
        print("\nYou can rerun this CLI after installing the missing tools.")
        return False
    return True


def prompt_stack_choice() -> StackOption:
    print("Select the stack configuration:\n")
    for idx, option in enumerate(STACK_OPTIONS, start=1):
        print(f" {idx:2d}) {option.label}")
    print()

    while True:
        choice = input("Enter option number: ").strip()
        if not choice.isdigit():
            print("Please enter a numeric choice.")
            continue
        idx = int(choice)
        if 1 <= idx <= len(STACK_OPTIONS):
            return STACK_OPTIONS[idx - 1]
        print("Choice out of range. Try again.")


def prompt_non_empty(prompt: str) -> str:
    while True:
        value = input(prompt).strip()
        if value:
            return value
        print("Value cannot be empty. Try again.")


def prompt_yes_no(question: str, default: bool = True) -> bool:
    suffix = "[Y/n]" if default else "[y/N]"
    while True:
        answer = input(f"{question} {suffix} ").strip().lower()
        if not answer:
            return default
        if answer in {"y", "yes"}:
            return True
        if answer in {"n", "no"}:
            return False
        print("Please answer with 'y' or 'n'.")


def git_clone_template(target_dir: Path, repo_url: str = TEMPLATE_REPO_URL) -> Path:
    if target_dir.exists():
        raise BootstrapError(f"Target directory {target_dir} already exists.")
    parent = target_dir.parent
    temp_dir = parent / DEFAULT_TEMPLATE_DIRNAME
    if temp_dir.exists():
        raise BootstrapError(f"Temporary path {temp_dir} already exists. Please remove it first.")
    run_command(["git", "clone", repo_url], cwd=parent)
    temp_dir.rename(target_dir)
    return target_dir


def replace_placeholders(root: Path, replacements: Dict[str, str], extensions: Iterable[str] = (".ts", ".js", ".json", ".txt", ".html", ".css", ".md", ".yaml", ".yml")) -> None:
    for path in root.rglob("*"):
        if path.is_file() and path.suffix.lower() in extensions:
            try:
                content = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
            original = content
            for old, new in replacements.items():
                content = content.replace(old, new)
            if content != original:
                path.write_text(content, encoding="utf-8")


def create_firebase_project(project_id: str, display_name: str) -> None:
    print(f"\nCreating Firebase project '{project_id}'...")
    result = run_command(
        ["firebase", "projects:create", project_id, "--display-name", display_name, "--quiet"],
        check=False,
    )
    if result.returncode != 0:
        print("Firebase project creation may have failed or already exist. Please verify manually.")


def enable_firestore(project_id: str) -> None:
    print(f"\nEnabling Firestore for '{project_id}' (if not already enabled)...")
    run_command(
        ["firebase", "firestore:databases:create", "--project", project_id, "(default)"],
        check=False,
    )


def create_firebase_hosting_sites(project_id: str, environments: Sequence[str]) -> Dict[str, str]:
    env_sites = {}
    for env in environments:
        if env == "local":
            continue
        site_id = f"{project_id}-{env}"
        print(f"\nCreating Firebase Hosting site '{site_id}'...")
        result = run_command(
            ["firebase", "hosting:sites:create", site_id, "--project", project_id],
            check=False,
        )
        if result.returncode != 0:
            print(f"  Skipped or failed for {site_id}. Verify manually.")
        env_sites[env] = site_id
    return env_sites


def update_firebaserc(root: Path, firebase_project_id: str, env_sites: Dict[str, str]) -> None:
    firebaserc = root / ".firebaserc"
    if not firebaserc.exists():
        print("Warning: .firebaserc not found; skipping update.")
        return
    data = json.loads(firebaserc.read_text(encoding="utf-8"))
    data.setdefault("projects", {})["default"] = firebase_project_id
    targets = data.setdefault("targets", {}).setdefault(firebase_project_id, {})
    hosting_targets = targets.setdefault("hosting", {})
    for env, site_id in env_sites.items():
        hosting_targets[env] = [
            site_id,
        ]
    firebaserc.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def update_firebase_json(root: Path, project_id: str, env_sites: Dict[str, str]) -> None:
    firebase_json = root / "firebase.json"
    if not firebase_json.exists():
        print("Warning: firebase.json not found; skipping update.")
        return
    data = json.loads(firebase_json.read_text(encoding="utf-8"))
    hosting_configs = data.get("hosting")
    if isinstance(hosting_configs, dict):
        hosting_configs = [hosting_configs]
    if not isinstance(hosting_configs, list):
        print("Warning: firebase.json hosting structure not recognised; skipping update.")
        return

    updated = False
    for cfg in hosting_configs:
        site = cfg.get("site")
        if site:
            env = site.replace(f"{project_id}-", "")
            if env in env_sites:
                cfg["site"] = env_sites[env]
                updated = True

    if updated:
        firebase_json.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def update_environment_files(root: Path, internal_name: str, features: Set[str]) -> None:
    env_dir = root / "src" / "environments"
    if not env_dir.exists():
        log_remaining("Review environment configuration files (src/environments) manually.")
        return

    env_files = list(env_dir.glob("environment*.ts"))
    if not env_files:
        log_remaining("Environment files missing under src/environments; configure manually.")
        return

    def desired_api_url(env: str) -> str:
        if env == "local":
            return "http://localhost:3000"
        if "node_api" in features:
            return f"https://{internal_name}-{env}.onrender.com"
        return "http://localhost:2829" if env == "local" else "https://api.example.com"

    def desired_cdn_url(env: str) -> str:
        if env == "local":
            return "http://localhost:2828"
        if "aws_s3" in features:
            return f"https://{internal_name}-{env}.s3.{AWS_REGION}.amazonaws.com"
        return f"https://{internal_name}-{env}.web.app"

    for path in env_files:
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue

        env_name = "prod"
        if "development" in path.name:
            env_name = "development"
        elif "local" in path.name:
            env_name = "local"
        elif "beta" in path.name:
            env_name = "beta"
        elif "production" in path.name:
            env_name = "prod"

        updated = text
        updated = updated.replace('ENVIRONMENT_NAME: \'prod\'', f"ENVIRONMENT_NAME: '{env_name}'")
        updated = updated.replace("ENVIRONMENT_NAME: \"prod\"", f'ENVIRONMENT_NAME: "{env_name}"')

        updated = updated.replace('API_URL: \'http://localhost:2829\'', f"API_URL: '{desired_api_url(env_name)}'")
        updated = updated.replace('API_URL: "http://localhost:2829"', f'API_URL: "{desired_api_url(env_name)}"')

        updated = updated.replace('CDN_URL: \'http://localhost:2828\'', f"CDN_URL: '{desired_cdn_url(env_name)}'")
        updated = updated.replace('CDN_URL: "http://localhost:2828"', f'CDN_URL: "{desired_cdn_url(env_name)}"')

        if updated != text:
            path.write_text(updated, encoding="utf-8")



def copy_build_directories(root: Path, internal_name: str, environments: Sequence[str]) -> None:
    build_dir = root / ".build"
    template_dir = build_dir / "EXAMPLE-web-site-01"
    if not template_dir.exists():
        print("Warning: .build/EXAMPLE-web-site-01 not found; skipping build dir duplication.")
        return
    for env in environments:
        if env == "local":
            continue
        destination = build_dir / f"{internal_name}-{env}"
        if destination.exists():
            print(f"  Build directory {destination} already exists. Skipping.")
            continue
        shutil.copytree(template_dir, destination)


def create_s3_buckets(internal_name: str, environments: Sequence[str]) -> None:
    for env in environments:
        if env == "local":
            continue
        bucket_name = f"{internal_name}-{env}"
        print(f"\nCreating S3 bucket '{bucket_name}' in {AWS_REGION}...")
        create_cmd = [
            "aws",
            "s3api",
            "create-bucket",
            "--bucket",
            bucket_name,
            "--region",
            AWS_REGION,
            "--create-bucket-configuration",
            f"LocationConstraint={AWS_REGION}",
        ]
        result = run_command(create_cmd, check=False)
        if result.returncode != 0:
            print(f"  Creation failed or bucket exists. Verify manually.")

        policy = {
            "Version": "2012-10-17",
            "Statement": [
                {
                    "Sid": "AllowPublicRead",
                    "Effect": "Allow",
                    "Principal": "*",
                    "Action": ["s3:GetObject"],
                    "Resource": [f"arn:aws:s3:::{bucket_name}/public/*"],
                }
            ],
        }
        policy_path = Path(f"./{bucket_name}-policy.json")
        policy_path.write_text(json.dumps(policy, indent=2), encoding="utf-8")
        print(f"  Applying public-read policy to {bucket_name}...")
        run_command(
            ["aws", "s3api", "put-bucket-policy", "--bucket", bucket_name, "--policy", str(policy_path.resolve())],
            check=False,
        )
        policy_path.unlink(missing_ok=True)

        cors_rules = {
            "CORSRules": [
                {
                    "AllowedHeaders": ["*"],
                    "AllowedMethods": ["GET", "HEAD"],
                    "AllowedOrigins": ["*"],
                    "ExposeHeaders": ["ETag"],
                    "MaxAgeSeconds": 3600,
                }
            ]
        }
        cors_path = Path(f"./{bucket_name}-cors.json")
        cors_path.write_text(json.dumps(cors_rules, indent=2), encoding="utf-8")
        print(f"  Applying permissive CORS to {bucket_name}...")
        run_command(
            ["aws", "s3api", "put-bucket-cors", "--bucket", bucket_name, "--cors-configuration", str(cors_path.resolve())],
            check=False,
        )
        cors_path.unlink(missing_ok=True)


def render_api_request(method: str, path: str, api_key: str, payload: Optional[dict] = None) -> Tuple[int, str]:
    url = f"https://api.render.com{path}"
    data = None
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, method=method.upper())
    req.add_header("Authorization", f"Bearer {api_key}")
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req) as response:
            return response.getcode(), response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8")
        return exc.code, body


def configure_render_services(
    internal_name: str,
    environments: Sequence[str],
    repo_url: str,
    branch: str,
    root_dir: str,
    build_command: str,
    start_command: str,
) -> None:
    api_key = os.environ.get("RENDER_API_KEY")
    if not api_key:
        log_remaining(
            "Create Render.com Node API services manually (set RENDER_API_KEY to automate)."
        )
        return

    for env in environments:
        if env == "local":
            continue
        service_name = f"{internal_name}-{env}-api"
        payload = {
            "name": service_name,
            "type": "web_service",
            "plan": RENDER_DEFAULT_PLAN,
            "env": "node",
            "repo": repo_url,
            "branch": branch,
            "rootDir": root_dir,
            "buildCommand": build_command,
            "startCommand": start_command,
            "autoDeploy": True,
            "serviceDetails": {
                "env": "node",
            },
            "envVars": [
                {"key": "NODE_ENV", "value": env if env != "prod" else "production"},
            ],
        }
        print(f"\nCreating Render service '{service_name}'...")
        status, body = render_api_request("POST", "/v1/services", api_key, payload)
        if status not in (200, 201):
            print(f"  Render API responded with {status}: {body}")
            log_remaining(f"Review Render service '{service_name}' creation manually.")
        else:
            print(f"  Render service '{service_name}' created (or already exists).")


def godaddy_request(method: str, domain: str, path: str, api_key: str, api_secret: str, payload: Optional[list] = None) -> Tuple[int, str]:
    url = f"https://api.godaddy.com/v1/domains/{domain}{path}"
    data = None
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, method=method.upper())
    req.add_header("Content-Type", "application/json")
    req.add_header("Authorization", f"sso-key {api_key}:{api_secret}")
    try:
        with urllib.request.urlopen(req) as response:
            return response.getcode(), response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8")
        return exc.code, body


def configure_godaddy_dns(domain: str, internal_name: str, env_sites: Dict[str, str]) -> None:
    api_key = os.environ.get("GODADDY_API_KEY")
    api_secret = os.environ.get("GODADDY_API_SECRET")
    if not api_key or not api_secret:
        log_remaining(
            "Configure GoDaddy DNS records manually (set GODADDY_API_KEY / GODADDY_API_SECRET to automate)."
        )
        return

    records = [
        {"type": "A", "name": "@", "data": FIREBASE_HOSTING_IP, "ttl": 600},
        {"type": "CNAME", "name": "www", "data": FIREBASE_CNAME, "ttl": 600},
    ]

    beta_site = env_sites.get("beta")
    if beta_site:
        records.append(
            {
                "type": "CNAME",
                "name": "beta",
                "data": f"{beta_site}.web.app",
                "ttl": 600,
            }
        )

    print(f"\nUpdating GoDaddy DNS records for {domain}...")
    status, body = godaddy_request("PUT", domain, "/records", api_key, api_secret, records)
    if status not in (200, 201, 204):
        print(f"  GoDaddy API responded with {status}: {body}")
        log_remaining(f"Review DNS configuration for {domain} manually.")
    else:
        print("  GoDaddy DNS records updated.")




def summarise_dns_instructions(app_public_name: str, internal_name: str) -> None:
    print(
        textwrap.dedent(
            f"""
            DNS configuration reminder:
              - Point apex domain (e.g., {app_public_name}.com) to Firebase Hosting target `{internal_name}-prod`.
              - Create subdomain `beta.{app_public_name}.com` pointing to `{internal_name}-beta`.
              - Configure both in GoDaddy (or registrar) AND in Firebase Hosting custom domains.
            """
        )
    )


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Bootstrap a new Angular + Tailwind project with optional extras.")
    parser.add_argument(
        "--template-url",
        default=TEMPLATE_REPO_URL,
        help=f"Template repository URL (default: {TEMPLATE_REPO_URL})",
    )
    parser.add_argument(
        "--output-dir",
        default=".",
        help="Directory where the new project will be created (default: current directory)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show actions without executing commands that mutate remote services.",
    )
    args = parser.parse_args(argv)

    stack = prompt_stack_choice()
    print(f"\nSelected stack: {stack.label}\nFeatures: {', '.join(sorted(stack.features)) or 'angular + tailwindcss'}\n")

    if not validate_prerequisites(stack.features):
        return 1

    app_internal_name = prompt_non_empty("Internal app name (e.g., app-internal-name-01): ")
    app_public_name = prompt_non_empty("Public app name (e.g., App Public Name): ")
    repo_parent = Path(args.output_dir).expanduser().resolve()
    project_dir = repo_parent / app_internal_name

    should_clone = prompt_yes_no(f"\nClone template repository into {project_dir}?")
    if should_clone:
        git_clone_template(project_dir, repo_url=args.template_url)
    else:
        if not project_dir.exists():
            raise BootstrapError(f"Directory {project_dir} does not exist.")

    replacements = {
        DEFAULT_PLACEHOLDER_INTERNAL: app_internal_name,
        DEFAULT_PLACEHOLDER_INTERNAL.upper(): app_internal_name.upper(),
        DEFAULT_PLACEHOLDER_INTERNAL_CAMEL: app_internal_name.replace("-", " ").title().replace(" ", ""),
        DEFAULT_PLACEHOLDER_PUBLIC: app_public_name.replace(" ", ""),
        DEFAULT_PLACEHOLDER_PUBLIC_NAME: app_public_name,
    }

    print("\nUpdating placeholders throughout the repository...")
    replace_placeholders(project_dir, replacements)
    update_environment_files(project_dir, app_internal_name, stack.features)

    firebase_project_id = prompt_non_empty("\nFirebase project id (e.g., app-internal-name-01): ")
    if not args.dry_run:
        create_firebase_project(firebase_project_id, app_public_name)
        if "firestore" in stack.features:
            enable_firestore(firebase_project_id)
        env_sites = create_firebase_hosting_sites(firebase_project_id, ENVIRONMENTS)
        update_firebaserc(project_dir, firebase_project_id, env_sites)
        update_firebase_json(project_dir, firebase_project_id, env_sites)
    else:
        print("Dry-run enabled: skipping Firebase project/site creation.")
        env_sites = {}

    copy_build_directories(project_dir, app_internal_name, ENVIRONMENTS)

    if "aws_s3" in stack.features:
        if not args.dry_run:
            create_s3_buckets(app_internal_name, ENVIRONMENTS)
        else:
            print("Dry-run: skipping S3 bucket creation.")
            log_remaining("Create AWS S3 buckets (dry-run prevented automation).")
    else:
        print("\nAWS S3 buckets not requested; skipping S3 steps.")

    if "node_api" in stack.features:
        service_repo = prompt_non_empty("\nNode API repository URL (e.g., https://github.com/user/app-api.git): ")
        service_branch = prompt_non_empty("Default branch for Render deployments (e.g., main): ")
        service_root = input("Root directory for API project (default '.'): ").strip() or "."
        build_command = input("Render build command (default: npm install && npm run build): ").strip() or "npm install && npm run build"
        start_command = input("Render start command (default: npm run start): ").strip() or "npm run start"
        if not args.dry_run:
            configure_render_services(
                app_internal_name,
                ENVIRONMENTS,
                service_repo,
                service_branch,
                service_root,
                build_command,
                start_command,
            )
        else:
            print("Dry-run: skipping Render service creation.")
            log_remaining("Create Render.com services (dry-run prevented automation).")
    else:
        print("\nNode API not selected; skipping Render automation.")

    domain_configured = False
    if env_sites and prompt_yes_no("\nConfigure GoDaddy DNS automatically?", default=False):
        domain_name = prompt_non_empty("Enter purchased domain (e.g., apppublicname.com): ")
        if not args.dry_run:
            configure_godaddy_dns(domain_name, app_internal_name, env_sites)
            domain_configured = True
        else:
            print("Dry-run: skipping DNS automation.")
            log_remaining("Configure GoDaddy DNS records (dry-run prevented automation).")
    elif env_sites:
        log_remaining("Configure GoDaddy DNS records (automation skipped by user).")

    if not domain_configured:
        summarise_dns_instructions(app_public_name, app_internal_name)

    log_remaining("Populate secrets and API keys (.env files, Firebase service accounts, Render deploy hooks).")
    log_remaining("Review Firebase Hosting / Storage rules and security settings.")

    if remaining_tasks:
        print("\nPending follow-up actions:")
        for item in remaining_tasks:
            print(f" - {item}")
        print()

    print("Bootstrap complete. Happy building!\n")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except BootstrapError as exc:
        print(f"\nError: {exc}", file=sys.stderr)
        sys.exit(1)
    except KeyboardInterrupt:
        print("\nAborted by user.")
        sys.exit(1)
def log_remaining(task: str) -> None:
    remaining_tasks.append(task)
