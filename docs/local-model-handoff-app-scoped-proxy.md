# Local Model Handoff — App-scoped Proxy

## 상위 작업자용 요약

브랜치: `gpt/app-scoped-proxy`
현재 HEAD(merge 직후): `0ea0bc1bfa6adda8efd73b4813059fcd88eaa564`

통합 상태:

- 프록시 구현 기준: `codex/review-workflow-acceleration` (`ef83d9eb720762a689f4518599533ab517c320cb`)
- 최신 리뷰 작업: `agent/review-workflow-acceleration-plan` (`4dbc4cfc088b7555147c6481f6c11bc67c072d6f`)
- 위 agent 브랜치를 PR #3으로 `gpt/app-scoped-proxy`에 merge 완료
- GitHub mergeability 확인 후 clean merge 되었고, agent 브랜치는 현재 `gpt/app-scoped-proxy`의 조상이다.
- merge 후 역비교 결과 agent 변경은 전부 포함되어 있고 app-scoped proxy 변경도 그대로 유지된다.

이미 구현된 범위:

- Windows 시스템 VPN/프록시 설정 변경 없음
- Catalogue Manager 전용 Chrome/Edge에만 command-line SOCKS5 proxy 적용
- Pybooru `proxies` 인자에만 local SOCKS endpoint 적용
- 인증형 upstream SOCKS5를 위한 loopback no-auth bridge 구현
- 실제 `input/network.env`는 Git ignore, example만 추적
- `requests[socks]` 의존성 추가
- direct/proxy IP 국가 + Danbooru HTTP를 한 번에 비교하는 `scripts\test_app_proxy.bat` 추가
- 관련 단위 테스트 추가
- 최신 리뷰의 `ReviewReferenceService`도 공용 `DanbooruClient`를 사용하므로 동일한 app-scoped proxy 경로를 사용한다.
- 최신 리뷰 UI의 Danbooru 링크는 Catalogue Manager 전용 브라우저의 `window.open`을 사용하므로 브라우저 proxy 적용 범위에 포함된다.

로컬 작업의 목적은 **재설계가 아니라 merge 후 Windows 실환경 검증**이다. 테스트가 통과하면 코드 수정하지 않는다.

---

## Worker A — 정적/단위/merge 회귀 검증

**권장 모델:** 사용 가능한 가장 저가형 Claude. Haiku급이 있으면 우선.  
**쓰기 권한:** 없음.  
**저장소 전체 탐색 금지.** 실패한 경우에만 관련 파일을 읽는다.

실행:

```bat
cd <repo-root>
scripts\setup.bat

.venv\Scripts\python.exe -m py_compile ^
  desktop\network_config.py ^
  desktop\socks_bridge.py ^
  desktop\app_launcher.py ^
  desktop\proxy_probe.py ^
  backend\app\integrations\danbooru\client.py ^
  backend\app\services\review_reference_service.py

.venv\Scripts\python.exe -m pytest ^
  desktop\tests\test_launcher.py ^
  desktop\tests\test_network_config.py ^
  desktop\tests\test_socks_bridge.py ^
  desktop\tests\test_app_launcher.py -q

pushd backend
..\.venv\Scripts\python.exe -m pytest ^
  tests\test_danbooru_proxy.py ^
  tests\test_review_reference_service.py -q
popd

pushd frontend
npm run build
popd
```

PASS 기준:

- Python compile 전체 성공
- 기존 desktop launcher + 새 proxy 테스트 성공
- Danbooru proxy 테스트 성공
- merge된 review reference service 테스트 성공
- frontend TypeScript/build 성공

보고 형식은 이것만 사용:

```text
WORKER_A
compile: PASS|FAIL
pytest_desktop: PASS|FAIL (<passed>/<failed>)
pytest_backend_proxy_review: PASS|FAIL (<passed>/<failed>)
frontend_build: PASS|FAIL
first_failure: <없으면 NONE, 있으면 첫 실패 traceback/build 오류 핵심 15줄 이내>
changed_files: NONE
```

PASS면 추가 분석 금지.

---

## 사용자 1회 입력 — 불가피한 자격 증명 설정

AI가 대신 만들거나 Git에 기록하지 않는다.

```bat
copy input\network.env.example input\network.env
```

`input/network.env`에서:

```dotenv
CATALOGUE_APP_PROXY_ENABLED=1
CATALOGUE_PROXY_UPSTREAM_HOST=<원하는 국가의 SOCKS5 endpoint>
CATALOGUE_PROXY_UPSTREAM_PORT=1080
CATALOGUE_PROXY_UPSTREAM_USERNAME=<service username>
CATALOGUE_PROXY_UPSTREAM_PASSWORD=<service password>
```

NordVPN이면 Nord Account의 **service credentials**를 사용한다. 일반 로그인 이메일/비밀번호를 넣지 않는다.

---

## Worker B — Windows 실제 네트워크 검증

**권장 모델:** 사용 가능한 가장 저가형 Claude.  
**쓰기 권한:** 없음.  
**선행 조건:** Worker A PASS + `input/network.env` 입력 완료.

저장소 분석 금지. 다음 명령만 수행한다.

### B1. direct/proxy 분리 확인

```bat
scripts\test_app_proxy.bat
```

PASS 기준:

- `direct` IP와 `proxy` IP가 다름
- `proxy` 국가가 사용자가 선택한 upstream 국가와 일치
- `Danbooru via proxy: HTTP 200`

### B2. 실제 Pybooru 확인

```bat
pushd backend
..\.venv\Scripts\python.exe -c "from app.integrations.danbooru.client import DanbooruClient; print(DanbooruClient().verify_credentials())"
popd
```

PASS 기준: `verified_via: pybooru` 결과가 출력되고 연결 오류가 없음.

### B3. 데스크톱 앱 + merge된 ReviewReference 경로 확인

```bat
scripts\launch_desktop.bat
```

앱 실행 후 PowerShell에서:

```powershell
Get-CimInstance Win32_Process -Filter "Name='chrome.exe' OR Name='msedge.exe'" |
  Where-Object { $_.CommandLine -and $_.CommandLine -match 'CatalogueManager.*browser-profile' } |
  Select-Object ProcessId, CommandLine
```

PASS 기준:

- Catalogue Manager 전용 브라우저 CommandLine에 `--proxy-server=socks5://127.0.0.1:<port>` 존재
- 앱 UI `127.0.0.1` 정상 표시
- 리뷰 화면 정상 진입
- 리뷰 reference image(Danbooru wiki/favorite) 로딩 정상
- 앱 내부 Danbooru Posts/Wiki 링크 정상 접속
- 일반 브라우저/다른 앱의 네트워크는 기존 상태 유지

보고 형식:

```text
WORKER_B
probe: PASS|FAIL
direct_country: <code>
proxy_country: <code>
danbooru_http: <status>
pybooru: PASS|FAIL
desktop_ui: PASS|FAIL
review_reference: PASS|FAIL
app_browser_proxy_flag: PASS|FAIL
normal_browser_unchanged: PASS|FAIL
first_failure: <없으면 NONE, 있으면 핵심 로그 15줄 이내>
changed_files: NONE
```

PASS면 종료. 추가 조사 금지.

---

## Worker C — 실패했을 때만 최소 수정

**권장 모델:** Claude Sonnet 계열. Worker A/B가 모두 PASS면 호출 금지.  
**입력:** 실패한 Worker의 보고서만 전달하고 전체 대화/전체 저장소를 다시 읽히지 않는다.

허용 파일:

- 시작/브라우저 실패: `desktop/app_launcher.py`, `scripts/launch_desktop.bat`
- SOCKS handshake/auth 실패: `desktop/socks_bridge.py`, `desktop/network_config.py`
- Pybooru proxy 실패: `backend/app/config.py`, `backend/app/integrations/danbooru/client.py`, `backend/requirements.txt`
- merge된 reference 경로 실패: `backend/app/services/review_reference_service.py` 또는 해당 frontend review 파일 중 실제 traceback/build 오류가 지목한 파일 1개
- probe만 실패: `desktop/proxy_probe.py`
- 해당 실패를 재현하는 테스트 파일 1개

금지:

- 무관한 frontend/backend 기능 탐색
- DB 변경
- 기존 Review/Generation/Collector의 대규모 리팩터링
- 시스템 VPN/Windows proxy 설정 변경
- `--dangerously-skip-permissions`, `bypassPermissions`
- commit/push/PR

수정 절차:

1. 받은 첫 실패를 재현한다.
2. 원인 파일 최대 2개만 수정한다.
3. 실패 테스트 + 관련 테스트만 재실행한다.
4. 수정 파일과 테스트 결과만 보고한다.

보고 형식:

```text
WORKER_C
root_cause: <2문장 이내>
changed_files:
- <path>
verification:
- <command>: PASS|FAIL
remaining_issue: NONE|<1문장>
```

---

## 상위 작업자 최종 판정

Worker A/B가 PASS면 추가 구현 없이 완료 처리한다.

Worker C가 발생했을 때만 상위 작업자가 해당 diff를 검수하고, 다음 조건을 다시 확인한다.

1. Windows 시스템 네트워크 설정을 건드리는 코드가 없음
2. Pybooru 이외 backend HTTP client에 global proxy 환경변수를 주입하지 않음
3. browser proxy는 Catalogue Manager 전용 Chrome/Edge process argument에만 존재
4. `input/network.env`가 추적되지 않음
5. merge된 `ReviewReferenceService`가 여전히 공용 `DanbooruClient` 경로를 사용함
6. frontend build와 review reference 테스트가 유지됨

최종 보고는 테스트 결과와 실제 proxy 국가만 남기고, 서비스 username/password는 절대 출력하지 않는다.
