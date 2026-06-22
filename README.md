# Catalogue Manager

Danbooru 캐릭터 카탈로그를 관리하는 데스크톱/GUI 애플리케이션입니다.

이 프로젝트는 **Python 가상환경(`.venv`)** 에서 실행하도록 구성되어 있습니다.  
공식 `scripts\*.bat` 스크립트는 모두 `.venv\Scripts\python.exe`를 사용합니다.

---

## 사전 요구 사항

| 항목 | 설명 |
|------|------|
| Python 3 | `python` 명령이 PATH에 있어야 합니다 |
| Node.js / npm | 프론트엔드 빌드 및 개발 서버용 |

---

## 1. 최초 1회 설정

프로젝트 루트에서 아래를 실행합니다.

```bat
scripts\setup.bat
```

이 스크립트가 하는 일:

1. `.venv` 가상환경 생성 (없을 때만)
2. `backend\requirements.txt` 의존성 설치
3. `frontend` npm 패키지 설치

설정이 끝나면 다음 경로가 생깁니다.

```
Catalogue_Manager\.venv\Scripts\python.exe
```

---

## 2. 앱 실행 (권장)

### 데스크톱 앱 (권장)

```bat
scripts\launch_desktop.bat
```

- `.venv` Python으로 `desktop\launcher.py` 실행
- 백엔드(FastAPI) + WebView2 GUI 창을 함께 띄움
- 창을 닫으면 백엔드도 함께 종료

### 개발 모드 (백엔드 + 프론트엔드 분리, 핫 리로드)

```bat
scripts\launch_app.bat
```

- 백엔드: `http://127.0.0.1:8000`
- 프론트엔드: `http://127.0.0.1:5173`
- 코드 수정 후 바로 반영할 때 사용

### 프로덕션 GUI (빌드된 프론트엔드)

```bat
scripts\launch_app_prod.bat
```

- 프론트엔드를 먼저 빌드한 뒤, 백엔드 하나로 GUI 제공

---

## 3. 앱 종료

```bat
scripts\stop_app.bat
```

포트 `8000`, `5173`을 사용 중인 프로세스를 종료합니다.

---

## 4. 가상환경에서 직접 명령 실행

공식 스크립트 대신 터미널에서 직접 실행할 때는 **먼저 가상환경을 활성화**하세요.

### PowerShell

```powershell
cd C:\Users\cwson\OneDrive\Desktop\Projects\Catalogue_Manager
.\.venv\Scripts\Activate.ps1
```

### CMD

```bat
cd C:\Users\cwson\OneDrive\Desktop\Projects\Catalogue_Manager
.venv\Scripts\activate.bat
```

프롬프트 앞에 `(.venv)` 가 보이면 활성화된 것입니다.

### 활성화 후 예시

```bat
cd backend
python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

```bat
cd frontend
npm run dev
```

> **주의:** 시스템 전역 `python`으로 실행하면 가상환경 밖에서 돌아갑니다.  
> 가능하면 `scripts\` 배치 파일을 쓰거나, 위처럼 `.venv`를 활성화한 뒤 실행하세요.

---

## 5. 가상환경 사용 여부 확인

### 방법 A — Python 경로 확인

가상환경이 활성화된 터미널에서:

```powershell
python -c "import sys; print(sys.executable)"
```

아래와 같이 `.venv\Scripts\python.exe` 가 출력되면 정상입니다.

```
...\Catalogue_Manager\.venv\Scripts\python.exe
```

### 방법 B — 실행 중인 프로세스 확인

```powershell
Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
  Where-Object { $_.CommandLine -match 'Catalogue_Manager|uvicorn' } |
  Select-Object ProcessId, CommandLine
```

`CommandLine`에 `.venv\Scripts\python.exe`가 포함되어 있으면 가상환경에서 실행 중입니다.

---

## 6. 자주 쓰는 유지보수 명령

모두 가상환경 Python(`.venv`)을 사용합니다.

| 목적 | 명령 |
|------|------|
| Danbooru API 설정 | `scripts\setup_danbooru.bat` |
| DB 초기화 (시리즈 목록 유지) | `scripts\reset_catalog.bat --skip-series-import` |
| DB 초기화 + `series.csv` 재로드 | `scripts\reset_catalog.bat` |
| CLI 캐릭터 수집 | `scripts\collect_characters.bat` |

---

## 7. 디렉터리 구조 (요약)

```
Catalogue_Manager/
├── .venv/              # Python 가상환경 (setup.bat으로 생성)
├── backend/            # FastAPI 백엔드
├── frontend/           # React 프론트엔드
├── desktop/            # pywebview 데스크톱 런처
├── scripts/            # 실행/설정 배치 파일
├── data/               # SQLite DB (catalogue.db)
├── input/              # series.csv, Danbooru 설정
└── output/             # 생성 이미지, 내보내기 등
```

---

## 8. 문제 해결

### `.venv`가 없다는 오류

```bat
scripts\setup.bat
```

### 포트가 이미 사용 중

```bat
scripts\stop_app.bat
```

그다음 다시 실행:

```bat
scripts\launch_desktop.bat
```

### PowerShell에서 activate가 막힐 때

```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
```

---

## 더 자세한 사용법

앱 내부 기능과 워크플로우는 [USAGE_GUIDE.md](USAGE_GUIDE.md)를 참고하세요.
