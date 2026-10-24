#!/usr/bin/env python3
"""CaptureKit - screenshot-capture spec runner for project READMEs.

Stdlib only, Python 3.10+.

CaptureKit does NOT capture screenshots itself on this machine. It:

* parses and validates a ``CAPTURE.md`` spec,
* generates a PowerShell script (``capture.ps1``) that SEAN runs on his
  Windows machine to take the actual captures,
* checks ("wire") whether the captured files exist and are referenced
  from a README, optionally inserting the references, and
* verifies (``verify``) that nothing is missing or unwired, for
  CI / pre-release checks.

Blur regions are spec annotations only. The generated script lists them
as post-step reminders; no image processing is performed anywhere in
this tool.
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

__version__ = "0.1.0"

REQUIRED_FIELDS = ("App", "Window", "Output", "Wait", "Notes")
SINGLE_FIELDS = ("App", "Window", "Output", "Wait", "Notes", "Region")
KNOWN_FIELDS = SINGLE_FIELDS + ("Blur",)


@dataclass
class Shot:
    """One screenshot described by a ``## <name>`` section."""

    name: str
    app: str = ""
    window: str = ""
    output: str = ""
    wait: float = 0.0
    notes: str = ""
    region: tuple[int, int, int, int] | None = None
    blur: list[tuple[int, int, int, int]] = field(default_factory=list)


def _parse_rect(value: str, shot_name: str, field_name: str, errors: list[str]):
    """Parse an ``x,y,w,h`` rectangle, appending a specific error on failure."""
    parts = [p.strip() for p in value.split(",")]
    if len(parts) != 4:
        errors.append(
            f"Shot '{shot_name}': invalid {field_name} '{value}' "
            f"(expected x,y,w,h - four comma-separated integers)"
        )
        return None
    try:
        nums = tuple(int(p) for p in parts)
    except ValueError:
        errors.append(
            f"Shot '{shot_name}': invalid {field_name} '{value}' "
            f"(expected x,y,w,h - four comma-separated integers)"
        )
        return None
    x, y, w, h = nums
    if w <= 0 or h <= 0:
        errors.append(
            f"Shot '{shot_name}': invalid {field_name} '{value}' "
            f"(width and height must be positive)"
        )
        return None
    return nums


def _parse_wait(value: str, shot_name: str, errors: list[str]):
    try:
        wait = float(value)
    except ValueError:
        errors.append(
            f"Shot '{shot_name}': invalid Wait '{value}' "
            f"(expected a number of seconds, e.g. 2 or 0.5)"
        )
        return None
    if wait < 0:
        errors.append(
            f"Shot '{shot_name}': invalid Wait '{value}' (must not be negative)"
        )
        return None
    # Keep integral waits as ints for tidy display / script generation.
    return int(wait) if wait == int(wait) else wait


def parse_spec(text: str) -> tuple[list[Shot], list[str]]:
    """Parse CAPTURE.md text.

    Returns ``(shots, errors)``. Shots that parse are returned even if
    other sections are malformed; every malformed section produces one
    or more specific error strings naming the shot and the problem.
    Content before the first ``##`` heading is treated as a preamble
    and ignored.
    """
    shots: list[Shot] = []
    errors: list[str] = []
    seen_names: set[str] = set()

    current_name: str | None = None
    current_fields: dict[str, list[str]] = {}

    def finish_section() -> None:
        if current_name is None:
            return
        name = current_name
        fields_map = current_fields
        if name in seen_names:
            errors.append(f"Shot '{name}': duplicate shot name")
            return
        seen_names.add(name)

        shot_errors_start = len(errors)

        # Unknown / duplicate single fields.
        for fname, values in fields_map.items():
            if fname not in KNOWN_FIELDS:
                errors.append(f"Shot '{name}': unknown field '{fname}'")
            elif fname in SINGLE_FIELDS and len(values) > 1:
                errors.append(f"Shot '{name}': duplicate field '{fname}'")

        # Missing required fields (absent or empty).
        for fname in REQUIRED_FIELDS:
            values = fields_map.get(fname)
            if not values or not values[0].strip():
                errors.append(f"Shot '{name}': missing required field '{fname}'")

        if len(errors) != shot_errors_start:
            # Still return a best-effort shot if it at least has an output?
            # No: a malformed shot should not silently be treated as valid.
            # Return it only when the sole problems are recorded above and
            # callers check errors; plan/gen refuse to proceed on errors.
            pass

        def first(fname: str) -> str:
            values = fields_map.get(fname)
            return values[0].strip() if values else ""

        shot = Shot(name=name)
        shot.app = first("App")
        shot.window = first("Window")
        shot.output = first("Output")
        shot.notes = first("Notes")

        wait_raw = first("Wait")
        if wait_raw:
            wait = _parse_wait(wait_raw, name, errors)
            if wait is not None:
                shot.wait = wait

        region_raw = first("Region")
        if region_raw:
            rect = _parse_rect(region_raw, name, "Region", errors)
            if rect is not None:
                shot.region = rect

        for blur_raw in fields_map.get("Blur", []):
            rect = _parse_rect(blur_raw.strip(), name, "Blur", errors)
            if rect is not None:
                shot.blur.append(rect)

        shots.append(shot)

    heading_re = re.compile(r"^##\s+(.+?)\s*$")
    bullet_re = re.compile(r"^[-*]\s+([^:]+):\s*(.*)$")

    for lineno, raw_line in enumerate(text.splitlines(), start=1):
        line = raw_line.rstrip()
        heading = heading_re.match(line)
        if heading:
            finish_section()
            current_name = heading.group(1).strip()
            current_fields = {}
            if not current_name:
                errors.append(f"Line {lineno}: empty shot name in '##' heading")
                current_name = None
            continue
        if current_name is None:
            continue  # preamble
        if not line.strip():
            continue
        bullet = bullet_re.match(line.strip())
        if bullet:
            fname = bullet.group(1).strip()
            fvalue = bullet.group(2).strip()
            current_fields.setdefault(fname, []).append(fvalue)
        else:
            errors.append(
                f"Shot '{current_name}': malformed line {lineno}: "
                f"{line.strip()!r} (expected '- Field: value')"
            )

    finish_section()

    if not shots and not errors:
        errors.append("No shots found (expected at least one '## <shot-name>' section)")

    return shots, errors


def load_spec(path: Path) -> tuple[list[Shot], list[str]]:
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return [], [f"Spec file not found: {path}"]
    except OSError as exc:
        return [], [f"Cannot read spec file {path}: {exc}"]
    return parse_spec(text)


# ---------------------------------------------------------------------------
# plan
# ---------------------------------------------------------------------------

def format_wait(wait) -> str:
    return f"{wait:g}" if isinstance(wait, float) else str(wait)


def cmd_plan(args) -> int:
    shots, errors = load_spec(Path(args.spec))
    if errors:
        print(f"Capture plan: {args.spec} - INVALID")
        for err in errors:
            print(f"  ERROR: {err}")
        return 1
    print(f"Capture plan: {args.spec} ({len(shots)} shot(s))")
    for i, shot in enumerate(shots, start=1):
        print(f"{i}. {shot.name}")
        print(f"   App: {shot.app}")
        print(f"   Window: {shot.window}")
        print(f"   Output: {shot.output}")
        print(f"   Wait: {format_wait(shot.wait)}s")
        print(f"   Notes: {shot.notes}")
        if shot.region is not None:
            print(f"   Region: {','.join(str(n) for n in shot.region)}")
        for rect in shot.blur:
            print(f"   Blur: {','.join(str(n) for n in rect)}")
    return 0


# ---------------------------------------------------------------------------
# gen-script
# ---------------------------------------------------------------------------

def ps_quote(value: str) -> str:
    """Quote a string as a PowerShell single-quoted literal."""
    return "'" + value.replace("'", "''") + "'"


def generate_script(shots: list[Shot], spec_name: str = "CAPTURE.md") -> str:
    lines: list[str] = []
    lines.append("# CaptureKit capture script - generated from " + spec_name)
    lines.append("# Run this on Windows (PowerShell 5.1 or 7+) from your project root.")
    lines.append("#")
    lines.append("# HONEST LIMITATIONS:")
    lines.append("# - Window positioning / activation is MANUAL unless a Region is")
    lines.append("#   given for a shot. Arrange the window described in each shot's")
    lines.append("#   notes before its Wait expires; the script only waits, then captures.")
    lines.append("# - Without a Region, the FULL primary screen is captured.")
    lines.append("#   With a Region, exactly that rectangle is captured.")
    lines.append("# - Blur regions are NOT applied by this script. They are listed")
    lines.append("#   per shot as post-step reminders: redact those rectangles in an")
    lines.append("#   image editor before publishing the screenshot.")
    lines.append("# - The Start-Process line per shot is best-effort: if the app is")
    lines.append("#   already running, comment that shot's Start-Process line out.")
    lines.append("")
    lines.append("$ErrorActionPreference = 'Continue'")
    lines.append("Add-Type -AssemblyName System.Drawing")
    lines.append("Add-Type -AssemblyName System.Windows.Forms")
    lines.append("")
    lines.append("function Save-Screenshot([int]$X, [int]$Y, [int]$W, [int]$H, [string]$Out) {")
    lines.append("    $dir = Split-Path -Parent $Out")
    lines.append("    if ($dir -and -not (Test-Path -LiteralPath $dir)) {")
    lines.append("        New-Item -ItemType Directory -Force -Path $dir | Out-Null")
    lines.append("    }")
    lines.append("    $bmp = New-Object System.Drawing.Bitmap $W, $H")
    lines.append("    $graphics = [System.Drawing.Graphics]::FromImage($bmp)")
    lines.append("    try {")
    lines.append("        $graphics.CopyFromScreen($X, $Y, 0, 0, $bmp.Size)")
    lines.append("        $bmp.Save($Out, [System.Drawing.Imaging.ImageFormat]::Png)")
    lines.append("        Write-Host \"Saved: $Out\"")
    lines.append("    } finally {")
    lines.append("        $graphics.Dispose()")
    lines.append("        $bmp.Dispose()")
    lines.append("    }")
    lines.append("}")
    lines.append("")

    for i, shot in enumerate(shots, start=1):
        lines.append(f"# --- Shot {i}: {shot.name} ---")
        lines.append(f"# Window: {shot.window}")
        lines.append(f"# Notes: {shot.notes}")
        lines.append(f"# Output: {shot.output}")
        if shot.region is not None:
            lines.append(f"# Region: {','.join(str(n) for n in shot.region)}")
        for rect in shot.blur:
            lines.append(
                f"# Blur (POST-STEP REMINDER, not applied): "
                f"{','.join(str(n) for n in rect)} - redact this area before publishing."
            )
        lines.append(f"Write-Host ''")
        lines.append(
            f"Write-Host {ps_quote(f'=== Shot {i}: {shot.name} ===')}"
        )
        lines.append(f"Write-Host {ps_quote('Arrange window: ' + shot.window)}")
        lines.append(f"Write-Host {ps_quote('Framing/state: ' + shot.notes)}")
        for rect in shot.blur:
            lines.append(
                "Write-Host "
                + ps_quote(
                    "Blur reminder (post-step, not automatic): "
                    + ",".join(str(n) for n in rect)
                )
            )
        lines.append(f"# Launch (best effort; skip if already running):")
        lines.append("try {")
        lines.append(f"    Start-Process -FilePath {ps_quote(shot.app)}")
        lines.append("} catch {")
        lines.append(
            f"    Write-Host {ps_quote('Could not launch ' + shot.app + ' - start it manually.')}"
        )
        lines.append("}")
        lines.append(f"Start-Sleep -Seconds {format_wait(shot.wait)}")
        lines.append(
            f"Write-Host {ps_quote('Capturing in 0s - make sure the window is arranged now.')}"
        )
        out_ps = ps_quote(shot.output)
        if shot.region is not None:
            x, y, w, h = shot.region
            lines.append(f"Save-Screenshot {x} {y} {w} {h} {out_ps}")
        else:
            lines.append("$bounds = [System.Windows.Forms.Screen]::PrimaryScreen.Bounds")
            lines.append(
                f"Save-Screenshot $bounds.X $bounds.Y $bounds.Width $bounds.Height {out_ps}"
            )
        lines.append("")

    lines.append("Write-Host ''")
    lines.append("Write-Host 'All shots attempted. Next: run capturekit wire / verify.'")
    lines.append(
        "Write-Host 'Reminder: apply any Blur redactions listed above before publishing.'"
    )
    lines.append("")
    return "\n".join(lines)


def cmd_gen_script(args) -> int:
    spec_path = Path(args.spec)
    shots, errors = load_spec(spec_path)
    if errors:
        print(f"Cannot generate script: {args.spec} is invalid:")
        for err in errors:
            print(f"  ERROR: {err}")
        return 1
    script = generate_script(shots, spec_name=spec_path.name)
    out = Path(args.out) if args.out else Path("capture.ps1")
    out.write_text(script, encoding="utf-8", newline="\n")
    print(f"Wrote {out} ({len(shots)} shot(s))")
    return 0


# ---------------------------------------------------------------------------
# wire / verify
# ---------------------------------------------------------------------------

@dataclass
class WireStatus:
    shot: Shot
    exists: bool
    wired: bool

    @property
    def ok(self) -> bool:
        return self.exists and self.wired


def _output_candidates(output: str, bases: list[Path]) -> list[Path]:
    p = Path(output)
    if p.is_absolute():
        return [p]
    return [base / p for base in bases]


def check_wire(shots, spec_path: Path, readme_path: Path) -> list[WireStatus]:
    bases: list[Path] = []
    for base in (readme_path.parent, spec_path.parent, Path.cwd()):
        if base not in bases:
            bases.append(base)
    try:
        readme_text = readme_path.read_text(encoding="utf-8")
    except OSError:
        readme_text = ""
    statuses: list[WireStatus] = []
    for shot in shots:
        exists = any(
            c.is_file() and c.stat().st_size > 0
            for c in _output_candidates(shot.output, bases)
        )
        # A reference counts in either slash direction (READMEs on GitHub
        # use forward slashes; a Windows-authored one might not).
        wired = (shot.output in readme_text) or (
            shot.output.replace("/", "\\") in readme_text
        )
        statuses.append(WireStatus(shot=shot, exists=exists, wired=wired))
    return statuses


def markdown_line(shot: Shot) -> str:
    return f"![{shot.name}]({shot.output})"


def format_wire_report(statuses: list[WireStatus]) -> list[str]:
    out: list[str] = []
    for st in statuses:
        exists_word = "OK" if st.exists else "MISSING"
        wired_word = "WIRED" if st.wired else "UNWIRED"
        out.append(f"{st.shot.name}: file={exists_word} readme={wired_word} ({st.shot.output})")
    return out


def apply_wire(statuses: list[WireStatus], readme_path: Path) -> list[str]:
    """Insert markdown lines for existing, not-yet-wired shots.

    Returns the lines added. Idempotent: a shot already referenced in
    the README is never added again.
    """
    to_add = [st.shot for st in statuses if st.exists and not st.wired]
    if not to_add:
        return []
    try:
        text = readme_path.read_text(encoding="utf-8")
    except OSError:
        text = ""
    new_lines = [markdown_line(s) for s in to_add]

    screenshots_idx = None
    license_idx = None
    lines = text.splitlines()
    for idx, line in enumerate(lines):
        stripped = line.strip()
        if stripped == "## Screenshots" and screenshots_idx is None:
            screenshots_idx = idx
        if stripped == "## License" and license_idx is None:
            license_idx = idx

    if screenshots_idx is not None:
        # Insert at the end of the existing Screenshots section.
        insert_at = len(lines)
        for idx in range(screenshots_idx + 1, len(lines)):
            if lines[idx].startswith("## "):
                insert_at = idx
                break
        # Trim trailing blank lines of the section, add lines, keep a blank.
        block = ["", *new_lines, ""]
        # Avoid doubling blank lines at EOF.
        new_text_lines = lines[:insert_at] + block + lines[insert_at:]
        new_text = "\n".join(new_text_lines).rstrip("\n") + "\n"
    elif license_idx is not None:
        block = ["## Screenshots", "", *new_lines, ""]
        new_text_lines = lines[:license_idx] + block + lines[license_idx:]
        new_text = "\n".join(new_text_lines).rstrip("\n") + "\n"
    else:
        base = text
        if base and not base.endswith("\n"):
            base += "\n"
        if base and not base.endswith("\n\n"):
            base += "\n"
        new_text = base + "## Screenshots\n\n" + "\n".join(new_lines) + "\n"

    readme_path.write_text(new_text, encoding="utf-8", newline="\n")
    return new_lines


def cmd_wire(args) -> int:
    spec_path = Path(args.spec)
    readme_path = Path(args.readme)
    shots, errors = load_spec(spec_path)
    if errors:
        print(f"Cannot wire: {args.spec} is invalid:")
        for err in errors:
            print(f"  ERROR: {err}")
        return 1
    statuses = check_wire(shots, spec_path, readme_path)
    for line in format_wire_report(statuses):
        print(line)

    if args.apply:
        added = apply_wire(statuses, readme_path)
        if added:
            print(f"Added {len(added)} line(s) to {readme_path}:")
            for line in added:
                print(f"  {line}")
        else:
            print("Nothing to add (all existing files already wired, or no files exist yet).")
        return 0

    pending = [st.shot for st in statuses if st.exists and not st.wired]
    if pending:
        print("")
        print("Markdown lines to add:")
        for shot in pending:
            print(markdown_line(shot))
    missing = [st.shot for st in statuses if not st.exists]
    if missing:
        print("")
        print("Not added (file missing):")
        for shot in missing:
            print(f"  {markdown_line(shot)}")
    return 0


def cmd_verify(args) -> int:
    spec_path = Path(args.spec)
    if getattr(args, "readme", None):
        readme_path = Path(args.readme)
    else:
        readme_path = spec_path.parent / "README.md"
    shots, errors = load_spec(spec_path)
    if errors:
        print(f"Verify FAILED: {args.spec} is invalid:")
        for err in errors:
            print(f"  ERROR: {err}")
        return 1
    statuses = check_wire(shots, spec_path, readme_path)
    bad = [st for st in statuses if not st.ok]
    if bad:
        print("Verify FAILED:")
        for st in bad:
            reasons = []
            if not st.exists:
                reasons.append("missing file")
            if not st.wired:
                reasons.append("not referenced in README")
            print(f"  {st.shot.name}: {', '.join(reasons)} ({st.shot.output})")
        return 1
    print(f"Verify OK: {len(statuses)} shot(s) present and wired.")
    return 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="capturekit",
        description="Screenshot-capture spec runner for project READMEs.",
    )
    parser.add_argument("--version", action="version", version=f"capturekit {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    p_plan = sub.add_parser("plan", help="Validate a CAPTURE.md and list its shots.")
    p_plan.add_argument("spec")
    p_plan.set_defaults(func=cmd_plan)

    p_gen = sub.add_parser("gen-script", help="Generate a Windows capture.ps1 from a CAPTURE.md.")
    p_gen.add_argument("spec")
    p_gen.add_argument("--out", default="capture.ps1")
    p_gen.set_defaults(func=cmd_gen_script)

    p_wire = sub.add_parser("wire", help="Check captured files against a README; optionally insert references.")
    p_wire.add_argument("spec")
    p_wire.add_argument("--readme", required=True)
    p_wire.add_argument("--apply", action="store_true")
    p_wire.set_defaults(func=cmd_wire)

    p_verify = sub.add_parser("verify", help="Exit 1 if any shot is missing or unwired.")
    p_verify.add_argument("spec")
    p_verify.add_argument("--readme", default=None,
                          help="README to check (default: README.md next to the spec).")
    p_verify.set_defaults(func=cmd_verify)

    return parser


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
