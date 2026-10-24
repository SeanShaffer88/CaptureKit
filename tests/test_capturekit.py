"""Tests for CaptureKit (unittest, tempfile only, stdlib only)."""
import io
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import capturekit
from capturekit import generate_script, markdown_line, parse_spec


FULL_SPEC = """# Capture spec

Intro text is ignored.

## main-window
- App: MyApp.exe
- Window: MyApp Main
- Output: docs/screenshots/main-window.png
- Wait: 2
- Notes: Maximized, default project open.

## settings-dialog
- App: MyApp.exe
- Window: Settings
- Output: docs/screenshots/settings.png
- Wait: 0.5
- Notes: Advanced section expanded.
"""

REGION_SPEC = """## tray-menu
- App: MyApp.exe
- Window: MyApp
- Output: docs/screenshots/tray.png
- Wait: 1
- Notes: Right-click tray icon first.
- Region: 100,200,640,480
- Blur: 10,10,200,30
- Blur: 0,400,640,80
"""

MALFORMED_SPEC = """## broken-shot
- App: MyApp.exe
- Window: MyApp
- Wait: not-a-number
- Notes: Missing its output.
"""

BAD_REGION_SPEC = """## bad-region
- App: MyApp.exe
- Window: MyApp
- Output: docs/screenshots/bad.png
- Wait: 1
- Notes: Bad region below.
- Region: 10,20,30
"""


def run_cli(argv):
    buf = io.StringIO()
    with redirect_stdout(buf):
        code = capturekit.main(argv)
    return code, buf.getvalue()


class ParserTests(unittest.TestCase):
    def test_full_spec(self):
        shots, errors = parse_spec(FULL_SPEC)
        self.assertEqual(errors, [])
        self.assertEqual(len(shots), 2)
        self.assertEqual(shots[0].name, "main-window")
        self.assertEqual(shots[0].app, "MyApp.exe")
        self.assertEqual(shots[0].window, "MyApp Main")
        self.assertEqual(shots[0].output, "docs/screenshots/main-window.png")
        self.assertEqual(shots[0].wait, 2)
        self.assertIn("Maximized", shots[0].notes)
        self.assertIsNone(shots[0].region)
        self.assertEqual(shots[0].blur, [])
        self.assertEqual(shots[1].wait, 0.5)

    def test_region_and_repeatable_blur(self):
        shots, errors = parse_spec(REGION_SPEC)
        self.assertEqual(errors, [])
        self.assertEqual(shots[0].region, (100, 200, 640, 480))
        self.assertEqual(shots[0].blur, [(10, 10, 200, 30), (0, 400, 640, 80)])

    def test_malformed_missing_output_and_bad_wait(self):
        shots, errors = parse_spec(MALFORMED_SPEC)
        joined = "\n".join(errors)
        self.assertIn("missing required field 'Output'", joined)
        self.assertIn("broken-shot", joined)
        self.assertIn("invalid Wait", joined)
        self.assertIn("not-a-number", joined)

    def test_malformed_bad_region(self):
        shots, errors = parse_spec(BAD_REGION_SPEC)
        joined = "\n".join(errors)
        self.assertIn("invalid Region", joined)
        self.assertIn("bad-region", joined)

    def test_no_shots_is_error(self):
        shots, errors = parse_spec("# Nothing here\n")
        self.assertTrue(errors)


class PlanTests(unittest.TestCase):
    def test_plan_valid(self):
        with tempfile.TemporaryDirectory() as td:
            spec = Path(td) / "CAPTURE.md"
            spec.write_text(FULL_SPEC, encoding="utf-8")
            code, out = run_cli(["plan", str(spec)])
            self.assertEqual(code, 0)
            self.assertIn("1. main-window", out)
            self.assertIn("docs/screenshots/main-window.png", out)
            self.assertIn("2. settings-dialog", out)

    def test_plan_invalid_exits_1(self):
        with tempfile.TemporaryDirectory() as td:
            spec = Path(td) / "CAPTURE.md"
            spec.write_text(MALFORMED_SPEC, encoding="utf-8")
            code, out = run_cli(["plan", str(spec)])
            self.assertEqual(code, 1)
            self.assertIn("missing required field 'Output'", out)


class GenScriptTests(unittest.TestCase):
    def test_script_contents_and_escaping(self):
        spec_text = (
            "## o-brien\n"
            "- App: C:\\Tools\\Bob's App.exe\n"
            "- Window: Bob's Window\n"
            "- Output: docs/screenshots/o'brien.png\n"
            "- Wait: 3\n"
            "- Notes: It's open.\n"
        )
        shots, errors = parse_spec(spec_text)
        self.assertEqual(errors, [])
        script = generate_script(shots)
        # Each output path present (PowerShell-escaped).
        self.assertIn("docs/screenshots/o''brien.png", script)
        # System.Drawing fullscreen/region capture primitive.
        self.assertIn("CopyFromScreen", script)
        # Single quotes doubled, PowerShell style.
        self.assertIn("Bob''s App.exe", script)
        self.assertIn("Bob''s Window", script)
        self.assertIn("Start-Sleep -Seconds 3", script)
        self.assertIn("System.Drawing.Bitmap", script)

    def test_script_contains_every_output_and_region(self):
        shots, errors = parse_spec(FULL_SPEC + "\n" + REGION_SPEC)
        self.assertEqual(errors, [])
        script = generate_script(shots)
        for shot in shots:
            self.assertIn(shot.output, script)
        # Region shot uses explicit coordinates.
        self.assertIn("Save-Screenshot 100 200 640 480", script)
        # Honesty: blur is a reminder, not applied.
        self.assertIn("not applied", script.lower())

    def test_gen_script_cli_writes_file(self):
        with tempfile.TemporaryDirectory() as td:
            spec = Path(td) / "CAPTURE.md"
            spec.write_text(FULL_SPEC, encoding="utf-8")
            out_ps = Path(td) / "capture.ps1"
            code, out = run_cli(["gen-script", str(spec), "--out", str(out_ps)])
            self.assertEqual(code, 0)
            self.assertTrue(out_ps.is_file())
            self.assertIn("CopyFromScreen", out_ps.read_text(encoding="utf-8"))


def make_wire_fixture(td: Path):
    """One existing PNG + one missing PNG; README references neither."""
    spec = td / "CAPTURE.md"
    spec.write_text(FULL_SPEC, encoding="utf-8")
    shots_dir = td / "docs" / "screenshots"
    shots_dir.mkdir(parents=True)
    (shots_dir / "main-window.png").write_bytes(b"\x89PNG\r\n\x1a\nfake-but-nonzero")
    readme = td / "README.md"
    readme.write_text("# Demo\n\nHello.\n\n## License\n\nMIT\n", encoding="utf-8")
    return spec, readme


class WireTests(unittest.TestCase):
    def test_wire_report_existing_and_missing(self):
        with tempfile.TemporaryDirectory() as td:
            spec, readme = make_wire_fixture(Path(td))
            code, out = run_cli(["wire", str(spec), "--readme", str(readme)])
            self.assertEqual(code, 0)
            self.assertIn("main-window: file=OK readme=UNWIRED", out)
            self.assertIn("settings-dialog: file=MISSING readme=UNWIRED", out)
            # Exact markdown line offered for the existing file only as addable.
            self.assertIn(markdown_line(type("S", (), {"name": "main-window", "output": "docs/screenshots/main-window.png"})), out)
            self.assertIn("Not added (file missing)", out)

    def test_wire_apply_inserts_once_before_license_and_idempotent(self):
        with tempfile.TemporaryDirectory() as td:
            spec, readme = make_wire_fixture(Path(td))
            code, out = run_cli(["wire", str(spec), "--readme", str(readme), "--apply"])
            self.assertEqual(code, 0)
            text1 = readme.read_text(encoding="utf-8")
            self.assertIn("## Screenshots", text1)
            self.assertIn("![main-window](docs/screenshots/main-window.png)", text1)
            # Missing file must not be wired.
            self.assertNotIn("settings.png", text1)
            # Inserted before License.
            self.assertLess(text1.index("## Screenshots"), text1.index("## License"))
            # Second run: no duplication.
            code, out = run_cli(["wire", str(spec), "--readme", str(readme), "--apply"])
            self.assertEqual(code, 0)
            text2 = readme.read_text(encoding="utf-8")
            self.assertEqual(text1, text2)
            self.assertEqual(text2.count("![main-window]"), 1)

    def test_wire_apply_appends_when_no_license(self):
        with tempfile.TemporaryDirectory() as td:
            spec, readme = make_wire_fixture(Path(td))
            readme.write_text("# Demo\n\nHello.\n", encoding="utf-8")
            code, _ = run_cli(["wire", str(spec), "--readme", str(readme), "--apply"])
            self.assertEqual(code, 0)
            text = readme.read_text(encoding="utf-8")
            self.assertTrue(text.rstrip().endswith("![main-window](docs/screenshots/main-window.png)"))


class VerifyTests(unittest.TestCase):
    def test_verify_fails_when_missing_or_unwired(self):
        with tempfile.TemporaryDirectory() as td:
            spec, readme = make_wire_fixture(Path(td))
            code, out = run_cli(["verify", str(spec), "--readme", str(readme)])
            self.assertEqual(code, 1)
            self.assertIn("main-window", out)  # unwired
            self.assertIn("settings-dialog", out)  # missing + unwired

    def test_verify_passes_when_all_present_and_wired(self):
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            spec, readme = make_wire_fixture(td)
            # Create the second file too, then wire both.
            (td / "docs" / "screenshots" / "settings.png").write_bytes(b"x")
            code, _ = run_cli(["wire", str(spec), "--readme", str(readme), "--apply"])
            self.assertEqual(code, 0)
            code, out = run_cli(["verify", str(spec), "--readme", str(readme)])
            self.assertEqual(code, 0)
            self.assertIn("Verify OK", out)

    def test_verify_default_readme_next_to_spec(self):
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            spec, readme = make_wire_fixture(td)
            (td / "docs" / "screenshots" / "settings.png").write_bytes(b"x")
            run_cli(["wire", str(spec), "--readme", str(readme), "--apply"])
            code, out = run_cli(["verify", str(spec)])
            self.assertEqual(code, 0)


if __name__ == "__main__":
    unittest.main()
