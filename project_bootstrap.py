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
import tempfile
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Set, Tuple

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
DEFAULT_GITHUB_OWNER = "joveem"
REMOVABLE_DOMAIN_SUFFIXES: Set[str] = {
    "api",
    "apis",
    "ws",
    "service",
    "services",
    "client",
    "clients",
    "web",
    "fe",
    "be",
    "frontend",
    "backend",
    "front",
    "back",
    "app",
    "apps",
    "site",
    "sites",
}

remaining_tasks: List[str] = []


def log_remaining(task: str) -> None:
    remaining_tasks.append(task)


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


PLACEHOLDER_EXTENSIONS: Tuple[str, ...] = (
    ".ts",
    ".js",
    ".json",
    ".txt",
    ".html",
    ".css",
    ".md",
    ".yaml",
    ".yml",
)


@dataclass(frozen=True)
class NodeAPIConfig:
    repo_url: str
    branch: str
    root_dir: str
    build_command: str
    start_command: str


@dataclass
class UserConfig:
    stack: StackOption
    app_internal_name: str
    app_public_name: str
    repo_parent: Path
    project_dir: Path
    should_clone: bool
    firebase_project_id: str
    template_url: str
    dry_run: bool
    node_api: Optional[NodeAPIConfig] = None
    configure_dns: bool = False
    domain_name: Optional[str] = None
    frontend_subdir: str = "."


@dataclass
class Step:
    name: str
    action: Callable[["ExecutionContext"], None]
    rollback: Optional[Callable[["ExecutionContext"], None]] = None


@dataclass
class RollbackResult:
    step_name: str
    status: str
    detail: Optional[str] = None


class StepExecutionError(BootstrapError):
    def __init__(self, step_name: str, original: BaseException):
        message = f"Step '{step_name}' failed: {original}"
        super().__init__(message)
        self.step_name = step_name
        self.original = original


@dataclass
class ExecutionContext:
    args: argparse.Namespace
    config: UserConfig
    replacements: Dict[str, str]
    env_sites: Dict[str, str] = field(default_factory=dict)
    step_backups: Dict[str, Dict[Path, str]] = field(default_factory=dict)
    step_created_paths: Dict[str, List[Path]] = field(default_factory=dict)
    step_data: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    active_step: Optional[str] = None
    render_api_key: Optional[str] = field(default_factory=lambda: os.environ.get("RENDER_API_KEY"))
    godaddy_api_key: Optional[str] = field(default_factory=lambda: os.environ.get("GODADDY_API_KEY"))
    godaddy_api_secret: Optional[str] = field(default_factory=lambda: os.environ.get("GODADDY_API_SECRET"))
    domain_configured: bool = False
    render_owner_id: Optional[str] = None
    frontend_root: Optional[Path] = None

    def _require_active_step(self) -> str:
        if not self.active_step:
            raise RuntimeError("No active step assigned in execution context.")
        return self.active_step

    def record_file_backup(self, path: Path, original_content: str) -> None:
        step_name = self._require_active_step()
        backups = self.step_backups.setdefault(step_name, {})
        resolved = path.resolve()
        if resolved not in backups:
            backups[resolved] = original_content

    def restore_files(self) -> None:
        step_name = self._require_active_step()
        backups = self.step_backups.get(step_name, {})
        failures: List[str] = []
        for path, content in backups.items():
            try:
                path.write_text(content, encoding="utf-8")
            except Exception as exc:
                failures.append(f"{path}: {exc}")
        if failures:
            raise BootstrapError("Failed to restore files:\n" + "\n".join(failures))

    def record_created_path(self, path: Path) -> None:
        step_name = self._require_active_step()
        paths = self.step_created_paths.setdefault(step_name, [])
        paths.append(path.resolve())

    def remove_created_paths(self) -> None:
        step_name = self._require_active_step()
        paths = self.step_created_paths.get(step_name, [])
        failures: List[str] = []
        for path in reversed(paths):
            try:
                if path.is_dir():
                    shutil.rmtree(path)
                elif path.exists():
                    path.unlink()
            except Exception as exc:
                failures.append(f"{path}: {exc}")
        if failures:
            raise BootstrapError("Failed to remove generated paths:\n" + "\n".join(failures))

    def add_step_data(self, key: str, value: Any) -> None:
        step_name = self._require_active_step()
        data = self.step_data.setdefault(step_name, {})
        data[key] = value

    def get_step_data(
        self, key: Optional[str] = None, default: Any = None, step_name: Optional[str] = None
    ) -> Any:
        name = step_name or self._require_active_step()
        data = self.step_data.get(name, {})
        if key is None:
            return data
        return data.get(key, default)

    def require_frontend_root(self) -> Path:
        if self.frontend_root is None:
            raise BootstrapError("Angular project root has not been resolved.")
        return self.frontend_root


class StepExecutor:
    def __init__(self, steps: Sequence[Step]):
        self.steps = list(steps)
        self.completed: List[Step] = []

    def run(self, ctx: ExecutionContext) -> None:
        for step in self.steps:
            print(f"\n>>> {step.name}")
            ctx.active_step = step.name
            try:
                step.action(ctx)
            except BootstrapError as exc:
                raise StepExecutionError(step.name, exc) from exc
            except Exception as exc:
                raise StepExecutionError(step.name, exc) from exc
            finally:
                ctx.active_step = None
            self.completed.append(step)

    def rollback(self, ctx: ExecutionContext) -> List[RollbackResult]:
        results: List[RollbackResult] = []
        for step in reversed(self.completed):
            ctx.active_step = step.name
            if step.rollback is None:
                results.append(RollbackResult(step.name, "pending", "No rollback action defined."))
                ctx.active_step = None
                continue
            try:
                step.rollback(ctx)
            except BootstrapError as exc:
                results.append(RollbackResult(step.name, "pending", str(exc)))
            except Exception as exc:
                results.append(RollbackResult(step.name, "pending", str(exc)))
            else:
                results.append(RollbackResult(step.name, "success"))
            finally:
                ctx.active_step = None
        return results


@dataclass
class PromptOutcome:
    action: str
    value: Any = None


@dataclass
class PromptRecord:
    prompt_id: str
    request: str
    default: Optional[str] = None
    value: Any = None
    summary_text: Optional[str] = None
    summary_lines: int = 0
    prompt_lines: int = 0
    redo_pending: bool = False


def _enable_ansi_sequences() -> bool:
    if os.name != "nt":
        return True
    try:
        import ctypes

        kernel32 = ctypes.windll.kernel32
        handle = kernel32.GetStdHandle(-11)  # STD_OUTPUT_HANDLE
        mode = ctypes.c_ulong()
        if not kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
            return False
        if not kernel32.SetConsoleMode(handle, mode.value | 0x0004):
            return False
        return True
    except Exception:
        return False


class PromptManager:
    YELLOW = "\033[33m"
    WHITE = "\033[37m"
    RESET = "\033[0m"

    def __init__(self) -> None:
        self.history: List[PromptRecord] = []
        self.records: Dict[str, PromptRecord] = {}
        self.cursor: int = 0
        self.ansi_supported: bool = _enable_ansi_sequences()

    def reset(self) -> None:
        self.history.clear()
        self.records.clear()
        self.cursor = 0

    def remove_record(self, prompt_id: str) -> None:
        record = self.records.pop(prompt_id, None)
        if not record:
            return
        try:
            idx = self.history.index(record)
        except ValueError:
            return
        self._clear_summary(record)
        self.history.pop(idx)
        if self.cursor > idx:
            self.cursor = max(self.cursor - 1, 0)

    def prompt_text(
        self,
        prompt_id: str,
        request: str,
        default: Optional[str] = None,
        allow_empty: bool = False,
        validator: Optional[Callable[[str], Tuple[bool, Any, Optional[str]]]] = None,
        summary_formatter: Optional[Callable[[Any], str]] = None,
        extra_lines: Optional[Iterable[str]] = None,
    ) -> PromptOutcome:
        return self._prompt(
            prompt_id,
            request,
            default,
            allow_empty=allow_empty,
            validator=validator,
            summary_formatter=summary_formatter,
            extra_lines=list(extra_lines) if extra_lines else [],
        )

    def prompt_yes_no(
        self,
        prompt_id: str,
        request: str,
        default: bool = True,
    ) -> PromptOutcome:
        default_text = "y" if default else "n"

        def validator(raw: str) -> Tuple[bool, Any, Optional[str]]:
            lowered = raw.lower()
            if lowered in {"y", "yes"}:
                return True, True, None
            if lowered in {"n", "no"}:
                return True, False, None
            return False, None, "Please answer with 'y' or 'n'."

        def formatter(value: Any) -> str:
            return "yes" if value else "no"

        return self._prompt(
            prompt_id,
            request,
            default_text,
            allow_empty=True,
            validator=validator,
            summary_formatter=formatter,
            extra_lines=None,
        )

    def prompt_choice(
        self,
        prompt_id: str,
        request: str,
        options: Sequence[Tuple[str, str, Any]],
        default_option: Optional[str] = None,
    ) -> PromptOutcome:
        options_lines = [f" {key:>2}) {label}" for key, label, _ in options]

        value_by_key = {key: value for key, _, value in options}

        def validator(raw: str) -> Tuple[bool, Any, Optional[str]]:
            if raw in value_by_key:
                return True, value_by_key[raw], None
            return False, None, "Please choose one of the listed options."

        def formatter(value: Any) -> str:
            for key, label, candidate in options:
                if candidate == value:
                    return f"{label} (#{key})"
            return str(value)

        return self._prompt(
            prompt_id,
            request,
            default_option,
            allow_empty=False,
            validator=validator,
            summary_formatter=formatter,
            extra_lines=options_lines,
        )

    def _prompt(
        self,
        prompt_id: str,
        request: str,
        default: Optional[str],
        *,
        allow_empty: bool,
        validator: Optional[Callable[[str], Tuple[bool, Any, Optional[str]]]],
        summary_formatter: Optional[Callable[[Any], str]],
        extra_lines: Optional[List[str]],
    ) -> PromptOutcome:
        record, idx = self._ensure_record(prompt_id, request, default)

        while True:
            allow_undo = idx > 0
            allow_redo = record.redo_pending and record.value is not None

            spacing_lines = self._print_prompt_spacing()
            prompt_lines = self._print_prompt(record, request, default, allow_undo, allow_redo, extra_lines or [])
            total_prompt_lines = spacing_lines + prompt_lines
            record.prompt_lines = total_prompt_lines
            try:
                user_input = input("> ").strip()
            except EOFError:
                user_input = ""
            self._clear_prompt_lines(total_prompt_lines + 1)

            command = user_input.lower()
            if command == "--undo":
                if not allow_undo:
                    self._note("Already at the first step; cannot undo.")
                    continue
                self._handle_undo(idx, record)
                return PromptOutcome(action="undo")

            if command == "--redo":
                if allow_redo:
                    record.redo_pending = False
                    self.cursor = idx + 1
                    self._print_summary(record, request, default, summary_formatter)
                    return PromptOutcome(action="redo", value=record.value)
                self._note("Nothing to redo for this step.")
                continue

            if not user_input and default is not None:
                user_input = default

            if not user_input and not allow_empty:
                self._note("Value cannot be empty. Try again.")
                continue

            if validator:
                ok, normalized, error = validator(user_input)
                if not ok:
                    self._note(error or "Invalid value. Try again.")
                    continue
                value = normalized
            else:
                value = user_input

            record.value = value
            record.default = default
            record.redo_pending = False
            self.cursor = idx + 1
            record.summary_lines = self._print_summary(record, request, default, summary_formatter)
            return PromptOutcome(action="next", value=value)

    def _ensure_record(self, prompt_id: str, request: str, default: Optional[str]) -> Tuple[PromptRecord, int]:
        record = self.records.get(prompt_id)
        if record is None:
            record = PromptRecord(prompt_id=prompt_id, request=request, default=default)
            self.records[prompt_id] = record
            self.history.insert(self.cursor, record)
        else:
            record.request = request
            record.default = default

        try:
            idx = self.history.index(record)
        except ValueError:
            self.history.insert(self.cursor, record)
            idx = self.cursor
        self.cursor = idx
        return record, idx

    def _handle_undo(self, idx: int, record: PromptRecord) -> None:
        is_new_without_value = record.value is None
        if is_new_without_value:
            self.remove_record(record.prompt_id)
        else:
            record.redo_pending = True
            self._clear_summary(record)

        prev_idx = max(idx - 1, 0)
        if prev_idx < len(self.history):
            prev_record = self.history[prev_idx]
            self._clear_summary(prev_record)
            if prev_record.value is not None:
                prev_record.redo_pending = True
        self.cursor = prev_idx

    def _print_prompt(
        self,
        record: PromptRecord,
        request: str,
        default: Optional[str],
        allow_undo: bool,
        allow_redo: bool,
        extra_lines: List[str],
    ) -> int:
        request_line = self._format_request_line(request, default)
        lines = [request_line]
        if extra_lines:
            formatted_extras = (
                [self._apply_color(line, self.YELLOW) for line in extra_lines]
                if self.ansi_supported
                else extra_lines
            )
            lines.extend(formatted_extras)

        commands: List[str] = []
        if allow_undo:
            commands.append("--undo to revisit the previous step")
        if allow_redo:
            commands.append("--redo to keep the previous value")
        if commands:
            command_line = "Commands: " + "; ".join(commands)
            lines.append(self._apply_color(command_line, self.YELLOW) if self.ansi_supported else command_line)

        output = "\n".join(lines)
        print(output)
        return len(lines)

    def _format_summary_text(
        self,
        request: str,
        default: Optional[str],
        value: Any,
        summary_formatter: Optional[Callable[[Any], str]],
    ) -> str:
        summary_value = summary_formatter(value) if summary_formatter else str(value)
        compact_request = " ".join(request.replace("\n", " ").split())
        default_display = default if default is not None else ""
        if not self.ansi_supported:
            return f"{compact_request} [{default_display}] -> {summary_value}"

        request_colored = self._apply_color(compact_request, self.YELLOW)

        if default is None:
            default_section = ""
        else:
            default_section = (
                f" {self._apply_color('[', self.YELLOW)}"
                f"{self._apply_color(default_display, self.WHITE)}"
                f"{self._apply_color(']', self.YELLOW)}"
            )

        arrow = f" {self._apply_color('->', self.YELLOW)} "
        value_colored = self._apply_color(summary_value, self.WHITE)
        return f"{request_colored}{default_section}{arrow}{value_colored}"

    def _print_summary(
        self,
        record: PromptRecord,
        request: str,
        default: Optional[str],
        summary_formatter: Optional[Callable[[Any], str]],
    ) -> int:
        if record.value is None:
            return 0
        summary = self._format_summary_text(request, default, record.value, summary_formatter)
        record.summary_text = summary
        print()
        print(summary)
        return summary.count("\n") + 2

    def _clear_summary(self, record: PromptRecord) -> None:
        if record.summary_lines > 0:
            self._clear_lines(record.summary_lines)
            record.summary_lines = 0
            record.summary_text = None

    def clear_summary(self, prompt_id: str) -> None:
        record = self.records.get(prompt_id)
        if record:
            self._clear_summary(record)

    def _clear_prompt_lines(self, count: int) -> None:
        if count <= 0:
            return
        self._clear_lines(count)

    def _clear_lines(self, count: int) -> None:
        if not self.ansi_supported:
            return
        for _ in range(count):
            sys.stdout.write("\033[F\033[K")
        sys.stdout.flush()

    def _note(self, message: str) -> None:
        print(message)

    def _apply_color(self, text: str, color: str) -> str:
        if not self.ansi_supported or not text:
            return text
        return f"{color}{text}{self.RESET}"

    def _format_request_line(self, request: str, default: Optional[str]) -> str:
        clean_request = request.strip()
        if default is None:
            return self._apply_color(clean_request, self.YELLOW) if self.ansi_supported else clean_request

        if not self.ansi_supported:
            return f"{clean_request} (default: {default})"

        request_colored = self._apply_color(clean_request, self.YELLOW)
        prefix = self._apply_color(" (", self.YELLOW) + self._apply_color("default: ", self.YELLOW)
        default_colored = self._apply_color(default, self.WHITE)
        suffix = self._apply_color(")", self.YELLOW)
        return f"{request_colored}{prefix}{default_colored}{suffix}"

    def _print_prompt_spacing(self) -> int:
        if not self.history:
            return 0
        if not any(rec.summary_lines > 0 for rec in self.history):
            return 0
        print()
        print()
        return 2

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
    try:
        result = subprocess.run(command, cwd=cwd, text=True, capture_output=True)
    except FileNotFoundError as exc:
        raise BootstrapError(f"90-02 | Failed to execute command '{' '.join(command)}': {exc}") from exc
    except Exception as exc:
        raise BootstrapError(f"90-01 | Failed to execute command '{' '.join(command)}': {exc}") from exc

    if result.stdout:
        print(result.stdout)
    if result.stderr:
        print(result.stderr, file=sys.stderr)

    if check and result.returncode != 0:
        combined_output = (result.stderr or result.stdout or "").strip()
        extra = f"\n{combined_output}" if combined_output else ""
        raise BootstrapError(f"Command failed ({result.returncode}): {' '.join(command)}{extra}")
    return result


def is_command_missing_error(error: BootstrapError, command: str) -> bool:
    message = str(error)
    token = f"Failed to execute command '{command}"
    return message.startswith("90-02") and token in message


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


def replace_placeholders(
    root: Path,
    replacements: Dict[str, str],
    extensions: Iterable[str] = PLACEHOLDER_EXTENSIONS,
    ctx: Optional[ExecutionContext] = None,
) -> int:
    changed = 0
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
                if ctx is not None:
                    ctx.record_file_backup(path, original)
                path.write_text(content, encoding="utf-8")
                changed += 1
    return changed


def create_firebase_project(project_id: str, display_name: str) -> bool:
    print(f"\nCreating Firebase project '{project_id}'...")
    try:
        run_command(
            ["firebase", "projects:create", project_id, "--display-name", display_name, "--quiet"],
        )
        return True
    except BootstrapError as exc:
        if is_command_missing_error(exc, "firebase"):
            print("  Firebase CLI not available; skipping project creation.")
            log_remaining("Create Firebase project via Firebase CLI (command unavailable).")
            return False
        raise


def enable_firestore(project_id: str) -> bool:
    print(f"\nEnabling Firestore for '{project_id}' (if not already enabled)...")
    try:
        result = run_command(
            ["firebase", "firestore:databases:create", "--project", project_id, "(default)"],
            check=False,
        )
    except BootstrapError as exc:
        if is_command_missing_error(exc, "firebase"):
            print("  Firebase CLI not available; skipping Firestore enablement.")
            log_remaining("Enable Firestore database via Firebase CLI (command unavailable).")
            return False
        raise
    if result.returncode != 0:
        combined = (result.stderr or result.stdout or "").lower()
        if "already exists" in combined:
            print("  Firestore database already exists; continuing.")
            return False
        raise BootstrapError(f"Failed to enable Firestore: {result.stderr or result.stdout or 'unknown error'}")
    return True


def create_firebase_hosting_sites(project_id: str, environments: Sequence[str]) -> Tuple[Dict[str, str], List[str]]:
    env_sites = {}
    created_sites: List[str] = []
    for env in environments:
        if env == "local":
            continue
        site_id = f"{project_id}-{env}"
        print(f"\nCreating Firebase Hosting site '{site_id}'...")
        try:
            result = run_command(
                ["firebase", "hosting:sites:create", site_id, "--project", project_id],
                check=False,
            )
        except BootstrapError as exc:
            if is_command_missing_error(exc, "firebase"):
                print("  Firebase CLI not available; skipping Firebase Hosting site creation.")
                log_remaining("Create Firebase Hosting sites via Firebase CLI (command unavailable).")
                return env_sites, created_sites
            raise
        if result.returncode != 0:
            combined = (result.stderr or result.stdout or "").lower()
            if "already exists" in combined:
                print(f"  Hosting site {site_id} already exists; using existing site.")
            else:
                raise BootstrapError(
                    f"Failed to create Firebase Hosting site {site_id}: {result.stderr or result.stdout or 'unknown error'}"
                )
        else:
            created_sites.append(site_id)
        env_sites[env] = site_id
    return env_sites, created_sites


def update_firebaserc(
    root: Path, firebase_project_id: str, env_sites: Dict[str, str], ctx: Optional[ExecutionContext] = None
) -> bool:
    firebaserc = root / ".firebaserc"
    if not firebaserc.exists():
        print("Warning: .firebaserc not found; skipping update.")
        return False
    original = firebaserc.read_text(encoding="utf-8")
    data = json.loads(original)
    data.setdefault("projects", {})["default"] = firebase_project_id
    targets = data.setdefault("targets", {}).setdefault(firebase_project_id, {})
    hosting_targets = targets.setdefault("hosting", {})
    for env, site_id in env_sites.items():
        hosting_targets[env] = [
            site_id,
        ]
    updated = json.dumps(data, indent=2) + "\n"
    if updated != original:
        if ctx is not None:
            ctx.record_file_backup(firebaserc, original)
        firebaserc.write_text(updated, encoding="utf-8")
        return True
    return False


def update_firebase_json(
    root: Path, project_id: str, env_sites: Dict[str, str], ctx: Optional[ExecutionContext] = None
) -> bool:
    firebase_json = root / "firebase.json"
    if not firebase_json.exists():
        print("Warning: firebase.json not found; skipping update.")
        return False
    original = firebase_json.read_text(encoding="utf-8")
    data = json.loads(original)
    hosting_configs = data.get("hosting")
    if isinstance(hosting_configs, dict):
        hosting_configs = [hosting_configs]
    if not isinstance(hosting_configs, list):
        print("Warning: firebase.json hosting structure not recognised; skipping update.")
        return False

    updated = False
    for cfg in hosting_configs:
        site = cfg.get("site")
        if site:
            env = site.replace(f"{project_id}-", "")
            if env in env_sites:
                cfg["site"] = env_sites[env]
                updated = True

    if updated:
        new_content = json.dumps(data, indent=2) + "\n"
        if ctx is not None:
            ctx.record_file_backup(firebase_json, original)
        firebase_json.write_text(new_content, encoding="utf-8")
        return True
    return False


def update_environment_files(root: Path, internal_name: str, features: Set[str], ctx: Optional[ExecutionContext] = None) -> int:
    env_dir = root / "src" / "environments"
    if not env_dir.exists():
        log_remaining("Review environment configuration files (src/environments) manually.")
        return 0

    env_files = list(env_dir.glob("environment*.ts"))
    if not env_files:
        log_remaining("Environment files missing under src/environments; configure manually.")
        return 0

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

    updated_count = 0

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
        updated = updated.replace("ENVIRONMENT_NAME: 'prod'", f"ENVIRONMENT_NAME: '{env_name}'")
        updated = updated.replace('ENVIRONMENT_NAME: "prod"', f'ENVIRONMENT_NAME: "{env_name}"')

        updated = updated.replace("API_URL: 'http://localhost:2829'", f"API_URL: '{desired_api_url(env_name)}'")
        updated = updated.replace('API_URL: "http://localhost:2829"', f'API_URL: "{desired_api_url(env_name)}"')

        updated = updated.replace("CDN_URL: 'http://localhost:2828'", f"CDN_URL: '{desired_cdn_url(env_name)}'")
        updated = updated.replace('CDN_URL: "http://localhost:2828"', f'CDN_URL: "{desired_cdn_url(env_name)}"')

        if updated != text:
            if ctx is not None:
                ctx.record_file_backup(path, text)
            path.write_text(updated, encoding="utf-8")
            updated_count += 1
    return updated_count



def copy_build_directories(
    root: Path, internal_name: str, environments: Sequence[str], ctx: Optional[ExecutionContext] = None
) -> List[Path]:
    build_dir = root / ".build"
    template_dir = build_dir / "EXAMPLE-web-site-01"
    if not template_dir.exists():
        print("Warning: .build/EXAMPLE-web-site-01 not found; skipping build dir duplication.")
        return []
    created: List[Path] = []
    for env in environments:
        if env == "local":
            continue
        destination = build_dir / f"{internal_name}-{env}"
        if destination.exists():
            print(f"  Build directory {destination} already exists. Skipping.")
            continue
        shutil.copytree(template_dir, destination)
        if ctx is not None:
            ctx.record_created_path(destination)
        created.append(destination)
    return created


def create_s3_buckets(internal_name: str, environments: Sequence[str], ctx: Optional[ExecutionContext] = None) -> List[str]:
    created: List[str] = []
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir_path = Path(tmpdir)
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
                combined_output = (result.stderr or result.stdout or "").lower()
                if "bucketalreadyownedbyyou" in combined_output or "bucket already exists" in combined_output:
                    print(f"  Bucket {bucket_name} already exists; skipping creation.")
                    continue
                raise BootstrapError(f"Failed to create bucket {bucket_name}: {result.stderr or result.stdout or 'unknown error'}")

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
            policy_path = tmpdir_path / f"{bucket_name}-policy.json"
            policy_path.write_text(json.dumps(policy, indent=2), encoding="utf-8")
            print(f"  Applying public-read policy to {bucket_name}...")
            run_command(
                [
                    "aws",
                    "s3api",
                    "put-bucket-policy",
                    "--bucket",
                    bucket_name,
                    "--policy",
                    str(policy_path.resolve()),
                ]
            )

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
            cors_path = tmpdir_path / f"{bucket_name}-cors.json"
            cors_path.write_text(json.dumps(cors_rules, indent=2), encoding="utf-8")
            print(f"  Applying permissive CORS to {bucket_name}...")
            run_command(
                [
                    "aws",
                    "s3api",
                    "put-bucket-cors",
                    "--bucket",
                    bucket_name,
                    "--cors-configuration",
                    str(cors_path.resolve()),
                ]
            )
            created.append(bucket_name)
    return created


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


def fetch_render_owner_id(api_key: str, ctx: Optional[ExecutionContext] = None) -> Optional[str]:
    status, body = render_api_request("GET", "/v1/owners", api_key)
    if status != 200:
        message = f"Render API responded with {status}: {body}"
        raise BootstrapError(f"Failed to resolve Render owner id. {message}")
    try:
        data = json.loads(body)
    except json.JSONDecodeError as exc:
        raise BootstrapError(f"Render owner list response was not valid JSON: {exc}") from exc
    owners = data.get("owners") if isinstance(data, dict) else data
    if isinstance(owners, list) and owners:
        owner = owners[0]
        owner_id = owner.get("id") if isinstance(owner, dict) else None
    elif isinstance(data, list) and data:
        owner = data[0]
        owner_id = owner.get("id") if isinstance(owner, dict) else None
    else:
        owner_id = None
    if not owner_id:
        raise BootstrapError("Unable to determine Render owner id from API response.")
    if ctx is not None:
        ctx.render_owner_id = owner_id
    return owner_id


def configure_render_services(
    internal_name: str,
    environments: Sequence[str],
    repo_url: str,
    branch: str,
    root_dir: str,
    build_command: str,
    start_command: str,
    api_key: str,
    ctx: Optional[ExecutionContext] = None,
) -> List[str]:
    created_services: List[str] = []
    owner_id: Optional[str] = None
    if ctx and ctx.render_owner_id:
        owner_id = ctx.render_owner_id
    else:
        try:
            owner_id = fetch_render_owner_id(api_key, ctx)
        except BootstrapError as exc:
            if ctx:
                ctx.add_step_data("render_owner_error", str(exc))
            raise
    for env in environments:
        if env == "local":
            continue
        service_name = f"{internal_name}-{env}-api"
        service_details: Dict[str, Any] = {
            "env": "node",
            "buildCommand": build_command,
            "startCommand": start_command,
            "buildPlan": RENDER_DEFAULT_PLAN,
        }
        payload: Dict[str, Any] = {
            "name": service_name,
            "type": "web_service",
            "repo": repo_url,
            "branch": branch,
            "rootDir": root_dir,
            "autoDeploy": "yes",
            "serviceDetails": service_details,
            "ownerId": owner_id,
            "envVars": [
                {"key": "NODE_ENV", "value": "production" if env == "prod" else env},
            ],
        }
        print(f"\nCreating Render service '{service_name}'...")
        status, body = render_api_request("POST", "/v1/services", api_key, payload)
        if status not in (200, 201):
            lower_body = body.lower()
            if status == 409 or "already exists" in lower_body:
                print(f"  Render service '{service_name}' already exists; skipping.")
                continue
            raise BootstrapError(f"Render API responded with {status}: {body}")
        try:
            data = json.loads(body)
        except json.JSONDecodeError as exc:
            raise BootstrapError(f"Render API returned invalid JSON for '{service_name}': {exc}") from exc
        service_id = data.get("id")
        if not service_id:
            raise BootstrapError(f"Render API response missing service id for '{service_name}'.")
        created_services.append(service_id)
    return created_services


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


def configure_godaddy_dns(
    domain: str,
    internal_name: str,
    env_sites: Dict[str, str],
    api_key: str,
    api_secret: str,
    ctx: Optional[ExecutionContext] = None,
) -> List[dict]:
    status, body = godaddy_request("GET", domain, "/records", api_key, api_secret)
    if status != 200:
        raise BootstrapError(f"Failed to read existing DNS records ({status}): {body}")
    try:
        existing_records = json.loads(body)
    except json.JSONDecodeError as exc:
        raise BootstrapError(f"Could not parse existing GoDaddy records: {exc}") from exc

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
        raise BootstrapError(f"GoDaddy API responded with {status}: {body}")
    print("  GoDaddy DNS records updated.")
    return existing_records




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


def collect_user_config(args: argparse.Namespace) -> UserConfig:
    questionnaire = Questionnaire(args)
    return questionnaire.run()


def build_replacements(config: UserConfig) -> Dict[str, str]:
    internal = config.app_internal_name
    public = config.app_public_name
    replacements = {
        DEFAULT_PLACEHOLDER_INTERNAL: internal,
        DEFAULT_PLACEHOLDER_INTERNAL.upper(): internal.upper(),
        DEFAULT_PLACEHOLDER_INTERNAL_CAMEL: internal.replace("-", " ").title().replace(" ", ""),
        DEFAULT_PLACEHOLDER_PUBLIC: public.replace(" ", ""),
        DEFAULT_PLACEHOLDER_PUBLIC_NAME: public,
    }
    return replacements


def discover_angular_roots(base: Path) -> List[Path]:
    candidates: List[Path] = []
    for angular_file in base.rglob("angular.json"):
        if any(part.lower() == "node_modules" for part in angular_file.parts):
            continue
        resolved = angular_file.parent.resolve()
        if resolved not in candidates:
            candidates.append(resolved)
    return candidates


def _run_git_command(args: Sequence[str]) -> Optional[str]:
    try:
        result = subprocess.run(["git", *args], text=True, capture_output=True, check=False)
    except (FileNotFoundError, OSError):
        return None
    if result.returncode != 0:
        return None
    value = result.stdout.strip()
    return value or None


def _parse_github_owner_from_remote(remote_url: str) -> Optional[str]:
    remote_url = remote_url.strip()
    if not remote_url:
        return None
    if remote_url.startswith("git@"):
        _, remainder = remote_url.split(":", 1)
        owner = remainder.split("/", 1)[0]
        return owner or None
    if remote_url.startswith("https://") or remote_url.startswith("http://"):
        parts = remote_url.split("/")
        if len(parts) >= 4:
            return parts[3] or None
    return None


def detect_default_git_owner() -> str:
    env_keys = ["GITHUB_USER", "GIT_USER", "GIT_USERNAME"]
    for key in env_keys:
        value = os.environ.get(key)
        if value:
            return value.strip()

    for args in (
        ["config", "--get", "user.username"],
        ["config", "--get", "github.user"],
    ):
        value = _run_git_command(args)
        if value:
            return value

    remote_url = _run_git_command(["config", "--get", "remote.origin.url"])
    if remote_url:
        owner = _parse_github_owner_from_remote(remote_url)
        if owner:
            return owner

    return DEFAULT_GITHUB_OWNER


def _tokens_without_suffixes(internal_name: str) -> List[str]:
    tokens = [segment for segment in internal_name.split("-") if segment]
    while tokens:
        last = tokens[-1]
        lowered = last.lower()
        if lowered in REMOVABLE_DOMAIN_SUFFIXES:
            tokens.pop()
            continue
        if lowered.startswith("v") and lowered[1:].isdigit():
            tokens.pop()
            continue
        if lowered.isdigit():
            tokens.pop()
            continue
        break
    return tokens if tokens else [internal_name.replace("-", "")]


def generate_default_domain(internal_name: str) -> str:
    tokens = _tokens_without_suffixes(internal_name)
    domain_root = "".join(tokens).lower()
    if not domain_root:
        domain_root = internal_name.replace("-", "")
    return f"{domain_root}.com"


def insert_api_segment(internal_name: str) -> str:
    parts = [segment for segment in internal_name.split("-") if segment]
    if not parts:
        return internal_name
    if parts[-1].isdigit():
        return "-".join(parts[:-1] + ["api", parts[-1]])
    return "-".join(parts + ["api"])


def generate_default_api_repo(internal_name: str, owner: Optional[str] = None) -> str:
    repo_owner = owner or detect_default_git_owner()
    repo_name = insert_api_segment(internal_name)
    if not repo_name.endswith(".git"):
        repo_name_with_suffix = f"{repo_name}.git"
    else:
        repo_name_with_suffix = repo_name
    return f"git@github.com:{repo_owner}/{repo_name_with_suffix}"


class Questionnaire:
    NODE_STEPS: Tuple[str, ...] = (
        "node_repo",
        "node_branch",
        "node_root",
        "node_build",
        "node_start",
    )

    def __init__(self, args: argparse.Namespace) -> None:
        self.args = args
        self.prompt_manager = PromptManager()
        self.answers: Dict[str, Any] = {}
        self.stack: Optional[StackOption] = None
        self.repo_parent: Path = Path(args.output_dir).expanduser().resolve()
        self.default_owner: str = detect_default_git_owner()
        self.pending_internal_confirm: Optional[str] = None

    def run(self) -> UserConfig:
        steps: List[str] = [
            "stack",
            "app_internal_name",
            "app_public_name",
            "should_clone",
            "firebase_project",
            *self.NODE_STEPS,
            "frontend_subdir",
            "configure_dns",
            "domain_name",
        ]

        idx = 0
        while idx < len(steps):
            step_id = steps[idx]
            if not self._is_applicable(step_id):
                self.prompt_manager.remove_record(step_id)
                idx += 1
                continue

            outcome = self._dispatch(step_id)
            if outcome.action == "undo":
                if idx > 0:
                    idx -= 1
                continue
            if outcome.action in {"next", "redo"}:
                if outcome.value is not None:
                    self.answers[step_id] = outcome.value
                    if step_id == "stack":
                        self.stack = outcome.value
                idx += 1
                continue
            idx += 1

        return self._build_config()

    def _is_applicable(self, step_id: str) -> bool:
        features = self.stack.features if self.stack else set()
        if step_id in self.NODE_STEPS and "node_api" not in features:
            self.answers.pop(step_id, None)
            return False
        if step_id in {"configure_dns", "domain_name"} and self.args.dry_run:
            if step_id == "configure_dns":
                self.answers.pop("configure_dns", None)
            if step_id == "domain_name":
                self.answers.pop("domain_name", None)
            return False
        if step_id == "domain_name" and not self.answers.get("configure_dns"):
            self.answers.pop("domain_name", None)
            return False
        return True

    def _dispatch(self, step_id: str) -> PromptOutcome:
        if step_id == "stack":
            return self._ask_stack()
        if step_id == "app_internal_name":
            return self._ask_internal_name()
        if step_id == "app_public_name":
            return self._ask_public_name()
        if step_id == "should_clone":
            return self._ask_should_clone()
        if step_id == "firebase_project":
            return self._ask_firebase_project()
        if step_id == "node_repo":
            return self._ask_node_repo()
        if step_id == "node_branch":
            return self._ask_node_branch()
        if step_id == "node_root":
            return self._ask_node_root()
        if step_id == "node_build":
            return self._ask_node_build()
        if step_id == "node_start":
            return self._ask_node_start()
        if step_id == "frontend_subdir":
            return self._ask_frontend_subdir()
        if step_id == "configure_dns":
            return self._ask_configure_dns()
        if step_id == "domain_name":
            return self._ask_domain_name()
        return PromptOutcome(action="next", value=None)

    def _ask_stack(self) -> PromptOutcome:
        options = [(str(idx), option.label, option) for idx, option in enumerate(STACK_OPTIONS, start=1)]
        current = self.answers.get("stack")
        default = None
        if current:
            for key, _, option in options:
                if option == current:
                    default = key
                    break
        return self.prompt_manager.prompt_choice("stack", "Select the stack configuration:", options, default_option=default)

    def _ask_internal_name(self) -> PromptOutcome:
        while True:
            default_value = self.answers.get("app_internal_name") or self.pending_internal_confirm

            def validator(raw: str) -> Tuple[bool, Any, Optional[str]]:
                return (True, raw, None) if raw else (False, None, "Value cannot be empty. Try again.")

            outcome = self.prompt_manager.prompt_text(
                "app_internal_name",
                "Internal app name (e.g., app-internal-name-01):",
                default=default_value,
                allow_empty=False,
                validator=validator,
            )
            if outcome.action == "undo":
                self.pending_internal_confirm = None
                return outcome
            if outcome.action not in {"next", "redo"} or not outcome.value:
                return outcome

            value = outcome.value
            project_dir = self.repo_parent / value
            if project_dir.exists() and self.pending_internal_confirm != value:
                self.prompt_manager.clear_summary("app_internal_name")
                self.prompt_manager._note(
                    f"Directory {project_dir} already exists. Enter the same name again to confirm or choose a different name."
                )
                self.pending_internal_confirm = value
                continue

            self.pending_internal_confirm = None
            self.answers["app_internal_name"] = value
            return outcome

    def _ask_public_name(self) -> PromptOutcome:
        previous = self.answers.get("app_public_name")

        def validator(raw: str) -> Tuple[bool, Any, Optional[str]]:
            return (True, raw, None) if raw else (False, None, "Value cannot be empty. Try again.")

        return self.prompt_manager.prompt_text(
            "app_public_name",
            "Public app name (e.g., App Public Name):",
            default=previous,
            allow_empty=False,
            validator=validator,
        )

    def _ask_should_clone(self) -> PromptOutcome:
        internal_name = self.answers.get("app_internal_name", "<app>")
        project_dir = self.repo_parent / internal_name
        previous = self.answers.get("should_clone")
        default = previous if previous is not None else True
        request = f"Clone template repository into {project_dir}?"
        return self.prompt_manager.prompt_yes_no("should_clone", request, default=default)

    def _ask_firebase_project(self) -> PromptOutcome:
        internal_name = self.answers.get("app_internal_name", "")
        previous = self.answers.get("firebase_project")
        default = previous or internal_name or None

        def validator(raw: str) -> Tuple[bool, Any, Optional[str]]:
            return (True, raw, None) if raw else (False, None, "Value cannot be empty. Try again.")

        return self.prompt_manager.prompt_text(
            "firebase_project",
            "\nFirebase project id (e.g., app-internal-name-01):",
            default=default,
            allow_empty=False,
            validator=validator,
        )

    def _ask_node_repo(self) -> PromptOutcome:
        internal_name = self.answers.get("app_internal_name", "")
        previous = self.answers.get("node_repo")
        auto_default = generate_default_api_repo(internal_name, owner=self.default_owner) if internal_name else None
        default = previous or auto_default

        def validator(raw: str) -> Tuple[bool, Any, Optional[str]]:
            return (True, raw, None) if raw else (False, None, "Value cannot be empty. Try again.")

        return self.prompt_manager.prompt_text(
            "node_repo",
            "  Node API repository URL (e.g., https://github.com/user/app-api.git):",
            default=default,
            allow_empty=False,
            validator=validator,
        )

    def _ask_node_branch(self) -> PromptOutcome:
        previous = self.answers.get("node_branch")
        default = previous or "main-01"

        def validator(raw: str) -> Tuple[bool, Any, Optional[str]]:
            return (True, raw, None) if raw else (False, None, "Value cannot be empty. Try again.")

        return self.prompt_manager.prompt_text(
            "node_branch",
            "  Default branch for Render deployments (e.g., main):",
            default=default,
            allow_empty=False,
            validator=validator,
        )

    def _ask_node_root(self) -> PromptOutcome:
        previous = self.answers.get("node_root")
        default = previous or "."
        return self.prompt_manager.prompt_text(
            "node_root",
            "  Root directory for API project (default '.'):",
            default=default,
            allow_empty=True,
            validator=lambda raw: (True, raw or default, None),
        )

    def _ask_node_build(self) -> PromptOutcome:
        previous = self.answers.get("node_build")
        default = previous or "npm install && npm run build"
        return self.prompt_manager.prompt_text(
            "node_build",
            "  Render build command (default: npm install && npm run build):",
            default=default,
            allow_empty=True,
            validator=lambda raw: (True, raw or default, None),
        )

    def _ask_node_start(self) -> PromptOutcome:
        previous = self.answers.get("node_start")
        default = previous or "npm run start"
        return self.prompt_manager.prompt_text(
            "node_start",
            "  Render start command (default: npm run start):",
            default=default,
            allow_empty=True,
            validator=lambda raw: (True, raw or default, None),
        )

    def _ask_frontend_subdir(self) -> PromptOutcome:
        previous = self.answers.get("frontend_subdir")
        default = previous or "."
        return self.prompt_manager.prompt_text(
            "frontend_subdir",
            "\nAngular project root relative to repository (default '.'):",
            default=default,
            allow_empty=True,
            validator=lambda raw: (True, raw or default, None),
        )

    def _ask_configure_dns(self) -> PromptOutcome:
        previous = self.answers.get("configure_dns")
        default = previous if previous is not None else False
        return self.prompt_manager.prompt_yes_no(
            "configure_dns",
            "\nConfigure GoDaddy DNS automatically after hosting setup?",
            default=default,
        )

    def _ask_domain_name(self) -> PromptOutcome:
        internal_name = self.answers.get("app_internal_name", "")
        previous = self.answers.get("domain_name")
        auto_default = generate_default_domain(internal_name) if internal_name else None
        default = previous or auto_default

        def validator(raw: str) -> Tuple[bool, Any, Optional[str]]:
            return (True, raw, None) if raw else (False, None, "Value cannot be empty. Try again.")

        return self.prompt_manager.prompt_text(
            "domain_name",
            "Enter purchased domain (e.g., apppublicname.com):",
            default=default,
            allow_empty=False,
            validator=validator,
        )

    def _build_config(self) -> UserConfig:
        stack = self.answers.get("stack")
        internal_name = self.answers.get("app_internal_name")
        public_name = self.answers.get("app_public_name")
        firebase_project = self.answers.get("firebase_project")
        frontend_subdir = self.answers.get("frontend_subdir", ".")
        configure_dns = bool(self.answers.get("configure_dns"))
        domain_name = self.answers.get("domain_name") if configure_dns else None
        should_clone = bool(self.answers.get("should_clone", True))

        repo_parent = self.repo_parent
        project_dir = repo_parent / internal_name

        node_api_config: Optional[NodeAPIConfig] = None
        if stack and "node_api" in stack.features:
            node_api_config = NodeAPIConfig(
                repo_url=self.answers.get("node_repo"),
                branch=self.answers.get("node_branch"),
                root_dir=self.answers.get("node_root") or ".",
                build_command=self.answers.get("node_build") or "npm install && npm run build",
                start_command=self.answers.get("node_start") or "npm run start",
            )

        if not stack or not internal_name or not public_name or not firebase_project:
            raise BootstrapError("Questionnaire did not complete successfully. Please rerun the CLI.")

        return UserConfig(
            stack=stack,
            app_internal_name=internal_name,
            app_public_name=public_name,
            repo_parent=repo_parent,
            project_dir=project_dir,
            should_clone=should_clone,
            firebase_project_id=firebase_project,
            template_url=self.args.template_url,
            dry_run=self.args.dry_run,
            node_api=node_api_config,
            configure_dns=configure_dns,
            domain_name=domain_name,
            frontend_subdir=frontend_subdir,
        )


def delete_firebase_project(project_id: str) -> None:
    print(f"  Deleting Firebase project '{project_id}'...")
    run_command(["firebase", "projects:delete", project_id, "--force"])


def delete_firestore_database(project_id: str) -> None:
    print(f"  Deleting Firestore database for '{project_id}'...")
    run_command(["firebase", "firestore:databases:delete", "(default)", "--project", project_id, "--force"])


def delete_firebase_hosting_site(project_id: str, site_id: str) -> None:
    print(f"  Deleting Firebase Hosting site '{site_id}'...")
    run_command(["firebase", "hosting:sites:delete", site_id, "--project", project_id, "--force"])


def delete_s3_bucket(bucket_name: str) -> None:
    print(f"  Removing S3 bucket '{bucket_name}'...")
    run_command(["aws", "s3", "rb", f"s3://{bucket_name}", "--force"])


def render_delete_service(service_id: str, api_key: str) -> None:
    status, body = render_api_request("DELETE", f"/v1/services/{service_id}", api_key)
    if status not in (200, 202, 204):
        raise BootstrapError(f"Render API failed to delete service {service_id}: {status} {body}")


def restore_godaddy_records(domain: str, records: List[dict], api_key: str, api_secret: str) -> None:
    status, body = godaddy_request("PUT", domain, "/records", api_key, api_secret, records)
    if status not in (200, 201, 204):
        raise BootstrapError(f"GoDaddy API failed to restore DNS records ({status}): {body}")


def step_clone_repository(ctx: ExecutionContext) -> None:
    config = ctx.config
    if config.should_clone:
        print(f"\nCloning template repository into {config.project_dir}...")
        git_clone_template(config.project_dir, repo_url=config.template_url)
        ctx.add_step_data("cloned", True)
    else:
        print(f"\nUsing existing project directory {config.project_dir}")
        if not config.project_dir.exists():
            raise BootstrapError(f"Directory {config.project_dir} does not exist.")
        ctx.add_step_data("cloned", False)


def rollback_clone_repository(ctx: ExecutionContext) -> None:
    data = ctx.get_step_data()
    if not data.get("cloned"):
        return
    target = ctx.config.project_dir
    try:
        if target.exists():
            shutil.rmtree(target)
        temp_dir = target.parent / DEFAULT_TEMPLATE_DIRNAME
        if temp_dir.exists():
            shutil.rmtree(temp_dir)
    except Exception as exc:
        raise BootstrapError(f"Failed to remove cloned repository: {exc}") from exc


def step_resolve_frontend_root(ctx: ExecutionContext) -> None:
    project_dir = ctx.config.project_dir
    requested = ctx.config.frontend_subdir.strip()
    if requested in {"", ".", "./"}:
        requested_path = project_dir
    else:
        requested_path = (project_dir / requested).resolve()

    search_base = requested_path if requested_path.exists() else project_dir

    candidates: List[Path] = []
    if requested_path.exists() and (requested_path / "angular.json").exists():
        candidates = [requested_path]
    else:
        candidates = discover_angular_roots(search_base)
        if not candidates and search_base != project_dir:
            candidates = discover_angular_roots(project_dir)

    if not candidates:
        raise BootstrapError(
            f"Unable to locate Angular workspace (angular.json) under {search_base}. "
            "Provide the correct relative path when prompted."
        )
    if len(candidates) > 1:
        rel_candidates = []
        for path in candidates:
            try:
                rel_candidates.append(str(path.relative_to(project_dir)))
            except ValueError:
                rel_candidates.append(str(path))
        joined = ", ".join(rel_candidates)
        raise BootstrapError(
            "Multiple Angular workspaces detected: "
            f"{joined}. Please rerun and specify the desired angular project root."
        )

    frontend_root = candidates[0]
    ctx.frontend_root = frontend_root
    try:
        rel_path = frontend_root.relative_to(project_dir)
        display = "." if str(rel_path) == "." else str(rel_path)
    except ValueError:
        display = str(frontend_root)
    ctx.add_step_data("frontend_root", display)
    print(f"Angular project root resolved to: {display}")


def step_replace_placeholders(ctx: ExecutionContext) -> None:
    changed = replace_placeholders(ctx.config.project_dir, ctx.replacements, ctx=ctx)
    ctx.add_step_data("files_changed", changed)
    print(f"Updated placeholders in {changed} file(s).")


def rollback_restore_files(ctx: ExecutionContext) -> None:
    ctx.restore_files()


def step_update_environment_files(ctx: ExecutionContext) -> None:
    root = ctx.require_frontend_root()
    count = update_environment_files(root, ctx.config.app_internal_name, ctx.config.stack.features, ctx=ctx)
    ctx.add_step_data("files_updated", count)
    if count:
        print(f"Updated {count} environment file(s).")


def step_copy_build_directories(ctx: ExecutionContext) -> None:
    root = ctx.require_frontend_root()
    created = copy_build_directories(root, ctx.config.app_internal_name, ENVIRONMENTS, ctx=ctx)
    ctx.add_step_data("created_paths", [str(path) for path in created])
    if created:
        print(f"Duplicated {len(created)} build director{'ies' if len(created) != 1 else 'y'}.")


def rollback_remove_generated_paths(ctx: ExecutionContext) -> None:
    ctx.remove_created_paths()


def step_create_firebase_project(ctx: ExecutionContext) -> None:
    created = create_firebase_project(ctx.config.firebase_project_id, ctx.config.app_public_name)
    ctx.add_step_data("project_created", created)


def rollback_delete_firebase_project(ctx: ExecutionContext) -> None:
    if not ctx.get_step_data().get("project_created"):
        return
    delete_firebase_project(ctx.config.firebase_project_id)


def step_enable_firestore(ctx: ExecutionContext) -> None:
    enabled = enable_firestore(ctx.config.firebase_project_id)
    ctx.add_step_data("firestore_enabled", enabled)


def rollback_disable_firestore(ctx: ExecutionContext) -> None:
    if not ctx.get_step_data().get("firestore_enabled"):
        return
    delete_firestore_database(ctx.config.firebase_project_id)


def step_create_firebase_hosting_sites(ctx: ExecutionContext) -> None:
    env_sites, created_sites = create_firebase_hosting_sites(ctx.config.firebase_project_id, ENVIRONMENTS)
    ctx.env_sites.update(env_sites)
    ctx.add_step_data("created_sites", created_sites)


def rollback_delete_firebase_hosting_sites(ctx: ExecutionContext) -> None:
    project_id = ctx.config.firebase_project_id
    for site_id in ctx.get_step_data().get("created_sites", []):
        delete_firebase_hosting_site(project_id, site_id)


def step_update_firebase_configs(ctx: ExecutionContext) -> None:
    if not ctx.env_sites:
        print("No Firebase hosting sites detected; skipping Firebase config updates.")
        return
    root = ctx.require_frontend_root()
    firebaserc_updated = update_firebaserc(root, ctx.config.firebase_project_id, ctx.env_sites, ctx=ctx)
    firebase_json_updated = update_firebase_json(root, ctx.config.firebase_project_id, ctx.env_sites, ctx=ctx)
    ctx.add_step_data("firebaserc_updated", firebaserc_updated)
    ctx.add_step_data("firebase_json_updated", firebase_json_updated)
    if firebaserc_updated or firebase_json_updated:
        print("Firebase configuration files updated.")


def step_create_s3_buckets(ctx: ExecutionContext) -> None:
    buckets = create_s3_buckets(ctx.config.app_internal_name, ENVIRONMENTS)
    ctx.add_step_data("created_buckets", buckets)


def rollback_delete_s3_buckets(ctx: ExecutionContext) -> None:
    for bucket in ctx.get_step_data().get("created_buckets", []):
        delete_s3_bucket(bucket)


def step_configure_render_services(ctx: ExecutionContext) -> None:
    node_api = ctx.config.node_api
    if not node_api:
        raise BootstrapError("Node API configuration missing.")
    api_key = ctx.render_api_key
    if not api_key:
        raise BootstrapError("RENDER_API_KEY not available.")
    services = configure_render_services(
        ctx.config.app_internal_name,
        ENVIRONMENTS,
        node_api.repo_url,
        node_api.branch,
        node_api.root_dir,
        node_api.build_command,
        node_api.start_command,
        api_key,
    )
    ctx.add_step_data("created_services", services)


def rollback_delete_render_services(ctx: ExecutionContext) -> None:
    api_key = ctx.render_api_key
    if not api_key:
        raise BootstrapError("RENDER_API_KEY not available for rollback.")
    for service_id in ctx.get_step_data().get("created_services", []):
        render_delete_service(service_id, api_key)


def step_configure_godaddy_dns(ctx: ExecutionContext) -> None:
    if not ctx.config.domain_name:
        raise BootstrapError("Domain name not provided for DNS configuration.")
    api_key = ctx.godaddy_api_key
    api_secret = ctx.godaddy_api_secret
    if not api_key or not api_secret:
        raise BootstrapError("GoDaddy API credentials not available.")
    previous_records = configure_godaddy_dns(
        ctx.config.domain_name,
        ctx.config.app_internal_name,
        ctx.env_sites,
        api_key,
        api_secret,
    )
    ctx.add_step_data("previous_records", previous_records)
    ctx.domain_configured = True


def rollback_restore_godaddy_dns(ctx: ExecutionContext) -> None:
    api_key = ctx.godaddy_api_key
    api_secret = ctx.godaddy_api_secret
    if not api_key or not api_secret:
        raise BootstrapError("GoDaddy API credentials not available for rollback.")
    previous_records = ctx.get_step_data().get("previous_records")
    if previous_records is None:
        raise BootstrapError("Previous DNS records not captured; cannot restore.")
    restore_godaddy_records(ctx.config.domain_name, previous_records, api_key, api_secret)


def build_steps(ctx: ExecutionContext) -> List[Step]:
    steps: List[Step] = [
        Step("Clone template repository", step_clone_repository, rollback_clone_repository),
        Step("Resolve Angular project root", step_resolve_frontend_root),
        Step("Replace project placeholders", step_replace_placeholders, rollback_restore_files),
        Step("Update Angular environment files", step_update_environment_files, rollback_restore_files),
        Step("Copy build directories", step_copy_build_directories, rollback_remove_generated_paths),
    ]

    features = ctx.config.stack.features

    if ctx.config.dry_run:
        log_remaining("Create Firebase project (dry-run prevented automation).")
        if "firestore" in features:
            log_remaining("Enable Firestore (dry-run prevented automation).")
        log_remaining("Create Firebase Hosting sites (dry-run prevented automation).")
        log_remaining("Update Firebase configuration files (dry-run prevented automation).")
    else:
        steps.append(Step("Create Firebase project", step_create_firebase_project, rollback_delete_firebase_project))
        if "firestore" in features:
            steps.append(Step("Enable Firestore", step_enable_firestore, rollback_disable_firestore))
        steps.append(
            Step("Create Firebase Hosting sites", step_create_firebase_hosting_sites, rollback_delete_firebase_hosting_sites)
        )
        steps.append(Step("Update Firebase configuration files", step_update_firebase_configs, rollback_restore_files))

    if "aws_s3" in features:
        if ctx.config.dry_run:
            log_remaining("Create AWS S3 buckets (dry-run prevented automation).")
        else:
            steps.append(Step("Create AWS S3 buckets", step_create_s3_buckets, rollback_delete_s3_buckets))

    if "node_api" in features:
        if ctx.config.dry_run:
            log_remaining("Create Render.com services (dry-run prevented automation).")
        else:
            if ctx.render_api_key:
                steps.append(Step("Configure Render services", step_configure_render_services, rollback_delete_render_services))
            else:
                log_remaining("Create Render.com services (missing RENDER_API_KEY).")

    if ctx.config.configure_dns:
        if ctx.config.dry_run:
            log_remaining("Configure GoDaddy DNS records (dry-run prevented automation).")
        else:
            if ctx.godaddy_api_key and ctx.godaddy_api_secret:
                steps.append(Step("Configure GoDaddy DNS", step_configure_godaddy_dns, rollback_restore_godaddy_dns))
            else:
                log_remaining("Configure GoDaddy DNS records (missing GODADDY_API_KEY / GODADDY_API_SECRET).")

    return steps


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

    try:
        config = collect_user_config(args)
    except KeyboardInterrupt:
        print("\nAborted by user during input.")
        return 1

    features_display = ", ".join(sorted(config.stack.features)) or "angular + tailwindcss"
    print("\nConfiguration summary:")
    print(f" - Stack: {config.stack.label}")
    print(f" - Features: {features_display}")
    print(f" - Project directory: {config.project_dir}")
    print(f" - Angular project root: {config.frontend_subdir}")
    print(f" - Clone template: {'yes' if config.should_clone else 'no'}")
    print(f" - Firebase project id: {config.firebase_project_id}")
    if config.node_api:
        print(f" - Render repository: {config.node_api.repo_url} ({config.node_api.branch})")
    if config.configure_dns:
        print(f" - GoDaddy domain: {config.domain_name}")
    print(f" - Dry run mode: {'yes' if config.dry_run else 'no'}")

    if not validate_prerequisites(config.stack.features):
        return 1

    if not prompt_yes_no("\nProceed with automation steps now?", default=True):
        print("Aborted before executing automation.")
        return 0

    replacements = build_replacements(config)
    ctx = ExecutionContext(args=args, config=config, replacements=replacements)

    steps = build_steps(ctx)
    if not steps:
        print("No automation steps to execute.")
        return 0

    executor = StepExecutor(steps)
    print("\nStarting automation...\n")

    try:
        executor.run(ctx)
    except StepExecutionError as exc:
        rollback_results = executor.rollback(ctx)
        print("\nBootstrap failed.\n")
        print(f"Step in progress: {exc.step_name}")
        print(f"Error details: {exc.original}")
        if rollback_results:
            succeeded = [r for r in rollback_results if r.status == "success"]
            pending = [r for r in rollback_results if r.status != "success"]
            if succeeded:
                print("\nRollback succeeded for:")
                for item in succeeded:
                    print(f" - {item.step_name}")
            if pending:
                print("\nRollback pending for:")
                for item in pending:
                    detail = f" ({item.detail})" if item.detail else ""
                    print(f" - {item.step_name}{detail}")
        if remaining_tasks:
            print("\nPending follow-up actions:")
            for item in remaining_tasks:
                print(f" - {item}")
        return 1
    except KeyboardInterrupt:
        print("\nInterrupted by user. Attempting rollback...")
        rollback_results = executor.rollback(ctx)
        succeeded = [r for r in rollback_results if r.status == "success"]
        pending = [r for r in rollback_results if r.status != "success"]
        if succeeded:
            print("Rollback succeeded for:")
            for item in succeeded:
                print(f" - {item.step_name}")
        if pending:
            print("Rollback pending for:")
            for item in pending:
                detail = f" ({item.detail})" if item.detail else ""
                print(f" - {item.step_name}{detail}")
        return 1

    print("Automation complete.\n")
    if not ctx.domain_configured:
        summarise_dns_instructions(config.app_public_name, config.app_internal_name)

    log_remaining("Populate secrets and API keys (.env files, Firebase service accounts, Render deploy hooks).")
    log_remaining("Review Firebase Hosting / Storage rules and security settings.")

    if remaining_tasks:
        print("Pending follow-up actions:")
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
