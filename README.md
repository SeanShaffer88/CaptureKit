## TL;DR

CaptureKit turns a `CAPTURE.md` screenshot spec into a checklist, a Windows PowerShell capture script, and a README wiring/verification pass — so project screenshots are planned once, captured in one sitting on a real Windows machine, and never silently missing at release time. Python 3.10+, standard library only, zero dependencies.

```console
$ python capturekit.py plan CAPTURE.md
$ python capturekit.py gen-script CAPTURE.md --out capture.ps1   # run capture.ps1 on Windows
$ python capturekit.py wire CAPTURE.md --readme README.md
$ python capturekit.py wire CAPTURE.md --readme README.md --apply
$ python capturekit.py verify CAPTURE.md
```

## Why this exists

The standing rule for these projects is that every README carries screenshots from **real runs on SEAN's Windows machine**. This tool's host (a Linux VM) cannot render those GUIs, so captures used to be perpetually owed and tracked in prose: a tray crop here, a menu shot there, a download-in-flight shot somewhere else.

CaptureKit makes the owed list machine-readable. The spec says exactly what to shoot and how to frame it; the generated script does the mechanical part (launch, wait, capture, save to the right path); `wire` and `verify` close the loop in the README and in CI.

## The CAPTURE.md spec format

A `CAPTURE.md` is a Markdown file with **one `## <shot-name>` section per screenshot**. Each section is a bullet list of fields:

| Field | Required | Meaning |
|---|---|---|
| `- App: <command or exe path>` | yes | What to launch for this shot. |
| `- Window: <window title substring>` | yes | Which window to arrange / capture. Descriptive — see Limitations. |
| `- Output: docs/screenshots/<name>.png` | yes | Where the PNG goes, relative to the project root. |
| `- Wait: <seconds>` | yes | Seconds to wait after launch before capturing (integers or decimals, e.g. `2`, `0.5`). |
| `- Notes: <framing/state instructions>` | yes | Human framing instructions: state, size, data on screen. |
| `- Region: x,y,w,h` | no | Capture exactly this screen rectangle instead of the full screen. Four comma-separated integers; width/height must be positive. |
| `- Blur: x,y,w,h` | no, repeatable | Privacy region to redact **after** capture. See Limitations — this is an annotation, not image processing. |

Content before the first `##` heading is a preamble and is ignored. Unknown fields, duplicate single fields, missing required fields, a non-numeric `Wait`, or a malformed `Region`/`Blur` are reported as specific errors naming the shot (e.g. `Shot 'settings': missing required field 'Output'`), and `plan` exits 1.

### Complete example

```markdown
# Screenshots to capture

Run `python capturekit.py gen-script CAPTURE.md` and then execute the
generated capture.ps1 on Windows.

## main-window
- App: MyApp.exe
- Window: MyApp Main
- Output: docs/screenshots/main-window.png
- Wait: 2
- Notes: Maximized, default project open, no modal dialogs.

## settings-dialog
- App: MyApp.exe
- Window: Settings
- Output: docs/screenshots/settings.png
- Wait: 0.5
- Notes: Settings open on the Advanced section, scrolled to the top.

## tray-menu
- App: MyApp.exe
- Window: MyApp
- Output: docs/screenshots/tray-menu.png
- Wait: 1
- Notes: Right-click the tray icon first so the context menu is visible.
- Region: 1200,600,360,420
- Blur: 1210,610,200,24
```

This exact example also ships as [`examples/CAPTURE.md`](examples/CAPTURE.md).

## Commands

### `plan CAPTURE.md`

Validates the spec and prints the numbered shot list with each shot's app, window, output, wait, notes, and any region/blur entries. Exits 1 and prints every specific error if the spec is malformed.

### `gen-script CAPTURE.md [--out capture.ps1]`

Generates a PowerShell script (default output: `capture.ps1`). For each shot the script:

1. prints the shot number, window, framing notes, and any blur reminders as host messages (they are also comments in the script),
2. attempts to launch the `App` with `Start-Process` (best effort — if the app is already running, comment that shot's line out),
3. sleeps for the shot's `Wait`,
4. captures using `System.Drawing` / `CopyFromScreen` — the full primary screen, or the shot's `Region` rectangle — creating the output directory if needed, and saves the PNG to the shot's `Output` path.

Single quotes in app names, window titles, notes, and output paths are escaped the PowerShell way (doubled: `''`).

### `wire CAPTURE.md --readme README.md [--apply]`

For each shot, reports:

- `file=OK` / `file=MISSING` — the output file exists and is non-zero,
- `readme=WIRED` / `readme=UNWIRED` — the README references the output path.

Without `--apply`, it prints the report plus the exact Markdown lines to add (`![<name>](<output>)` for shots whose files exist), and lists the lines it will **not** add because the file is missing.

With `--apply`, it inserts those lines for **existing files only**: into the existing `## Screenshots` section if there is one, otherwise as a new `## Screenshots` section inserted before `## License` if present, otherwise appended at the end. It is idempotent — running it twice adds nothing twice.

### `verify CAPTURE.md [--readme README.md]`

Pre-release / CI check. Exits 0 when every shot's file exists, is non-zero, and is referenced from the README; otherwise exits 1 and lists each failing shot with its reasons (`missing file`, `not referenced in README`). `--readme` defaults to the `README.md` next to the spec.

## Workflow

1. **Plan** — write/maintain `CAPTURE.md` in the project root; run `plan` until it validates.
2. **Capture** — run `gen-script`, copy `capture.ps1` to the Windows machine, arrange each window as its notes describe during its wait, and let the script save the PNGs. Apply any `Blur` redactions in an image editor (see below).
3. **Wire** — run `wire` (report first), then `wire --apply` to insert the README references.
4. **Verify** — run `verify` before a release; wire it into CI if the project has one.

## Limitations

Stated plainly:

- **Capture itself runs on Windows, not here.** CaptureKit generates the script; the screenshots are taken when a human runs it on a real Windows machine with the real app. Nothing in this repository renders or fakes a GUI.
- **Window activation and framing are still human.** Unless a shot gives a `Region`, the script captures the full primary screen. Positioning the window, opening the right dialog/menu, and getting the described state on screen during the wait is a manual step — the script prints the notes to guide it, it does not drive the app's UI.
- **Blur is a spec annotation, not image processing.** A `Blur:` line records *where* a privacy redaction must happen. The generated script lists each blur region as a post-step reminder, and CaptureKit never opens, modifies, or blurs any image. Redact those rectangles in an image editor before publishing, and double-check the result by eye.
- **Window titles are descriptive only.** The `Window:` field is not used to find, focus, or crop to a window automatically.
- Paths are resolved for existence checks relative to the README's directory, then the spec's directory, then the current directory, which covers the usual project-root layout; exotic layouts may need captures moved into place by hand.

## Development

```console
$ python -m unittest discover -s tests -v
```

Zero dependencies; everything is the Python standard library. CI (`.github/workflows/ci.yml`) runs the test suite on Python 3.10 and 3.12.

## License

MIT — see [LICENSE](LICENSE). Copyright (c) 2026 Sean Shaffer.
