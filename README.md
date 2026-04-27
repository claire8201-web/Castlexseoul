# Castlexseoul

Castlexseoul golf reservation tool with a Tkinter desktop UI, Selenium-based booking automation, and a GitHub Releases launcher for free app updates.

## Main files

- `castlexseoul_v8.1.0.py`: main desktop reservation app
- `CastlexLauncher.py`: update launcher that checks GitHub Releases
- `GITHUB_RELEASES_UPDATE_GUIDE.md`: release and update workflow

## Build

```powershell
pyinstaller "castlexseoul_v8.1.0.spec" --noconfirm
pyinstaller "CastlexLauncher.spec" --noconfirm
powershell -ExecutionPolicy Bypass -File ".\Prepare-CastlexRelease.ps1"
```

## Update setup

1. Edit `launcher_config.json` with your GitHub owner and repo name.
2. Upload `CastlexSeoul.exe` and `version.json` to each GitHub Release.
3. Run `CastlexLauncher.exe` on user machines.
