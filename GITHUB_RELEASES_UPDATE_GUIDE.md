# GitHub Releases 자동 업데이트 운영 가이드

이 구조는 `CastlexLauncher.exe`가 GitHub Releases의 최신 릴리스를 확인하고, 필요하면 `CastlexSeoul.exe`를 내려받아 교체한 뒤 본앱을 실행하는 방식이다.

## 1. 준비

- GitHub에 공개 저장소를 하나 만든다.
- 이 폴더의 `launcher_config.json`에서 아래 값을 실제 저장소로 바꾼다.

```json
{
  "github_owner": "your-github-id",
  "github_repo": "your-public-repo",
  "app_asset_name": "CastlexSeoul.exe",
  "version_asset_name": "version.json"
}
```

- `CastlexLauncher.exe`는 이 설정을 읽어 최신 릴리스를 조회한다.

## 2. 빌드

본앱:

```powershell
pyinstaller "castlexseoul_v8.1.0.spec" --noconfirm
```

런처:

```powershell
pyinstaller "CastlexLauncher.spec" --noconfirm
```

배포 폴더 정리:

```powershell
powershell -ExecutionPolicy Bypass -File ".\Prepare-CastlexRelease.ps1"
```

빌드 결과:

- `dist/CastlexSeoul.exe`
- `dist/CastlexLauncher.exe`

## 3. 첫 배포

처음 사용자에게는 아래 4개 파일을 한 번 전달한다.

- `CastlexLauncher.exe`
- `launcher_config.json`
- `CastlexSeoul.exe`
- `app_version.json`
- 필요 시 기본 설정 파일

사용자는 이후부터 `CastlexLauncher.exe`만 실행하면 된다.

## 4. GitHub Release 올리는 방법

새 버전 배포 시 Release 자산에 아래 2개를 반드시 올린다.

- `CastlexSeoul.exe`
- `version.json`

`version.json` 예시:

```json
{
  "version": "8.1.1",
  "asset_name": "CastlexSeoul.exe",
  "notes": "달력 주차 표시 제거",
  "sha256": ""
}
```

권장 순서:

1. 본앱을 새 버전으로 빌드한다.
2. 필요하면 SHA256 값을 계산해 `version.json`에 넣는다.
3. GitHub에서 새 Release를 만든다.
4. 자산으로 `CastlexSeoul.exe`, `version.json`을 업로드한다.
5. 사용자는 다음 실행 시 자동으로 최신 버전을 받는다.

## 5. 기존 EXE 사용자 전환

기존에 `castlexseoul_v8_1_0.exe` 같은 구버전 단일 EXE만 쓰던 사용자는 자동 업데이트를 바로 받을 수 없다. 이 사용자들은 한 번은 수동 전환이 필요하다.

전환 방법:

1. 기존 EXE를 종료한다.
2. 새 배포본으로 아래 파일을 같은 폴더에 넣는다.
   - `CastlexLauncher.exe`
   - `launcher_config.json`
   - `CastlexSeoul.exe`
   - `app_version.json`
3. 이후부터는 기존 EXE 대신 `CastlexLauncher.exe`를 실행한다.
4. `user_config.json`, `credentials.enc.json`은 같은 폴더에 두면 그대로 유지된다.

중요:

- 예전 EXE 파일명은 자동 업데이트 대상이 아니다.
- 자동 업데이트는 고정 파일명 `CastlexSeoul.exe`를 기준으로 동작한다.
- 따라서 기존 사용자는 처음 한 번만 새 실행 구조로 갈아타면 된다.

## 6. 추천 배포 형태

가장 단순한 배포 폴더 예시:

```text
CastlexLauncher.exe
launcher_config.json
CastlexSeoul.exe
app_version.json
user_config.json
credentials.enc.json
```

사용자 안내 문구는 이렇게 주면 된다.

`앞으로는 CastlexLauncher.exe만 실행하세요. 프로그램은 실행 전에 최신 버전을 자동으로 확인합니다.`
