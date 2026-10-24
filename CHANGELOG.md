# Changelog

All notable changes to CaptureKit are documented here.

## 0.1.0 - 2026-10-24

- Initial release.
- `CAPTURE.md` spec format and parser: one `## <shot-name>` section per
  shot with `App`, `Window`, `Output`, `Wait`, and `Notes` fields, plus
  optional `Region` and repeatable `Blur` rectangles. Malformed sections
  produce specific, shot-named errors.
- `capturekit.py plan`: validate a spec and print the numbered shot list;
  exits 1 on errors.
- `capturekit.py gen-script`: generate a Windows PowerShell capture
  script (`System.Drawing` / `CopyFromScreen`, full screen or region,
  per-shot launch + wait, directories created, single quotes escaped).
  Window arrangement is manual and blur regions are emitted as post-step
  reminders — neither is faked.
- `capturekit.py wire`: report `OK`/`MISSING` and `WIRED`/`UNWIRED` per
  shot, print the exact Markdown lines to add, and with `--apply` insert
  them (existing `## Screenshots` section, or before `## License`, or
  appended) for existing files only. Idempotent.
- `capturekit.py verify`: exit 1 listing missing/unwired shots, for
  CI / pre-release checks.
- Test suite (unittest, stdlib only) covering the parser, plan,
  gen-script, wire, and verify paths.
