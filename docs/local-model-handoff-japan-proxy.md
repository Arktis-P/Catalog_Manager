# Local Handoff — Japan Proxy Validation

대상 브랜치: `gpt/app-scoped-proxy`

기존 `docs/local-model-handoff-app-scoped-proxy.md`의 검증 흐름은 유지하되, 네트워크 구성은 이 문서를 우선한다.

## 전제

현재 권장 모드는 `ssh`이며 목표 국가는 `JP`다. Catalogue Manager가 Windows `ssh.exe -D`를 자동 실행해 일본 SSH 호스트를 local SOCKS5 endpoint로 사용한다.

## 사용자에게 필요한 최소 작업

사용자가 일본/Tokyo Linux VPS를 준비한 뒤 다음을 1회 수행하도록 안내한다.

```bat
scripts\setup_japan_proxy.bat
```

열린 `input/network.env`에 아래 3개 placeholder만 실제 로컬 값으로 교체한다.

```text
CATALOGUE_PROXY_SSH_HOST
CATALOGUE_PROXY_SSH_USER
CATALOGUE_PROXY_SSH_KEY_FILE
```

그리고 `CATALOGUE_APP_PROXY_ENABLED=1`로 변경한다.

민감한 SSH private key 내용은 읽거나 출력하거나 Git에 기록하지 않는다.

## Worker A — 저가형 Claude

재설계 금지. 다음만 수행한다.

```bat
scripts\setup.bat

.venv\Scripts\python.exe -m py_compile ^
  desktop\network_config.py ^
  desktop\app_launcher.py ^
  desktop\proxy_probe.py ^
  desktop\socks_bridge.py

.venv\Scripts\python.exe -m pytest ^
  desktop\tests\test_network_config.py ^
  desktop\tests\test_app_launcher.py ^
  desktop\tests\test_socks_bridge.py -q

pushd backend
..\.venv\Scripts\python.exe -m pytest tests\test_danbooru_proxy.py tests\test_review_reference_service.py -q
popd

pushd frontend
npm run build
popd
```

PASS면 코드 수정 금지.

## Worker B — 실제 Windows/Japan 검증

사용자 설정 완료 후:

```bat
scripts\test_app_proxy.bat
```

PASS 기준:

- direct/proxy IP가 다름
- `proxy` country가 정확히 `JP`
- `Danbooru via proxy: HTTP 200`

그다음 실제 Pybooru:

```bat
pushd backend
..\.venv\Scripts\python.exe -c "from app.integrations.danbooru.client import DanbooruClient; print(DanbooruClient().verify_credentials())"
popd
```

마지막으로:

```bat
scripts\launch_desktop.bat
```

확인:

- 앱 UI 정상
- 전용 Chrome/Edge command line에 `--proxy-server=socks5://127.0.0.1:1080`
- 앱의 Danbooru Posts/Wiki 링크 정상
- 일반 브라우저의 공인 IP는 direct IP 그대로

보고 형식:

```text
JAPAN_PROXY_VALIDATION
static_tests: PASS|FAIL
proxy_probe: PASS|FAIL
direct_country: <code>
proxy_country: <code>
danbooru_http: <status>
pybooru: PASS|FAIL
desktop_ui: PASS|FAIL
normal_browser_unchanged: PASS|FAIL
first_failure: NONE|<핵심 오류>
```

모두 PASS면 종료. 추가 분석/리팩터링 금지.

## 실패 시

첫 실패 원인만 Claude Sonnet 계열에 전달한다. 전체 대화나 전체 저장소를 다시 읽히지 않는다.

- SSH 시작 실패 → `desktop/app_launcher.py`, `desktop/network_config.py`만
- JP 판정 실패 → 설정값/Tokyo host 먼저 확인; 코드 수정은 마지막
- Pybooru만 실패 → `backend/app/integrations/danbooru/client.py`만
- 브라우저만 실패 → `desktop/app_launcher.py`만

시스템 VPN/Windows proxy/라우팅 변경은 금지한다.
