# Local Model Handoff — App-scoped Proxy

> **현재 기본 목표는 일본(JP) 출구입니다.**
>
> 로컬 검증/작업은 `docs/local-model-handoff-japan-proxy.md`를 우선 사용하십시오.
> 이 문서는 과거 generic SOCKS5/NordVPN 흐름의 진입점으로만 남깁니다.

## 현재 권장 흐름

1. 브랜치 `gpt/app-scoped-proxy` 사용
2. `scripts\setup_japan_proxy.bat` 실행
3. 로컬 `input/network.env`에 일본 SSH host/user/key path만 입력
4. `docs/local-model-handoff-japan-proxy.md`의 Worker A 실행
5. Worker A PASS 후 Worker B 실행
6. `scripts\test_app_proxy.bat` 결과의 proxy country가 정확히 `JP`여야 PASS

## 유지되는 안전 조건

- Windows 시스템 VPN/프록시/DNS/라우팅 변경 금지
- Pybooru 이외 backend HTTP client에 global proxy 환경변수 주입 금지
- browser proxy는 Catalogue Manager 전용 Chrome/Edge process argument에만 적용
- `input/network.env` 및 SSH private key는 Git에 기록 금지
- 테스트가 PASS면 추가 리팩터링 금지

## Generic SOCKS5 fallback

일본 SOCKS5 provider를 별도로 사용할 경우 `input/network.env`에서:

```dotenv
CATALOGUE_APP_PROXY_MODE=socks5
CATALOGUE_PROXY_EXPECTED_COUNTRY=JP
```

로 변경하고 provider의 host/port/auth 정보를 로컬에서 입력할 수 있습니다. 이 경우에도 Worker B의 `JP` 국가 검증은 동일하게 적용합니다.
