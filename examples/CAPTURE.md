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
