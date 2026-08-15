# Catalogue Manager — App-scoped Proxy

## 목표

Windows 전체 VPN/프록시 설정을 변경하지 않고 다음 두 경로만 별도 지역의 SOCKS5 출구로 보냅니다.

1. Catalogue Manager 백엔드의 Danbooru/Pybooru API 요청
2. Catalogue Manager가 전용 프로필로 실행하는 Chrome/Edge의 외부 URL 요청

일반 Chrome/Edge, Cursor/Codex, Git, NAIA, Hugging Face 및 다른 프로그램은 기존 네트워크 경로를 유지합니다.

## 구조

```text
Windows system network (변경 없음)
├─ 일반 앱 / 일반 브라우저 --------------------------> 기존 인터넷
└─ Catalogue Manager
   ├─ FastAPI GUI 127.0.0.1 --------------------------> DIRECT
   ├─ Pybooru ----------------------------------------> 127.0.0.1 SOCKS5
   └─ 전용 Chrome/Edge --proxy-server=socks5://... ---> 127.0.0.1 SOCKS5
                                                        │
                                                        v
                                            authenticated SOCKS5 upstream
                                                        │
                                                        v
                                                target-region public IP
```

`desktop/socks_bridge.py`가 loopback에만 바인딩되는 무인증 SOCKS5 브리지를 만듭니다. Chrome은 SOCKS5 username/password 인증을 직접 지원하지 않으므로 브리지가 upstream 인증을 대신합니다.

## 설정

1. 의존성을 갱신합니다.

```bat
scripts\setup.bat
```

2. 로컬 설정 파일을 만듭니다.

```bat
copy input\network.env.example input\network.env
```

3. `input/network.env`를 편집합니다.

```dotenv
CATALOGUE_APP_PROXY_ENABLED=1
CATALOGUE_APP_PROXY_HOST=127.0.0.1
CATALOGUE_APP_PROXY_PORT=1080

CATALOGUE_PROXY_UPSTREAM_HOST=your.socks5.proxy
CATALOGUE_PROXY_UPSTREAM_PORT=1080
CATALOGUE_PROXY_UPSTREAM_USERNAME=your_service_username
CATALOGUE_PROXY_UPSTREAM_PASSWORD=your_service_password
```

인증이 없는 일반 SOCKS5 upstream이면 username/password는 비워도 됩니다.

NordVPN SOCKS5를 사용할 경우 Nord Account의 **service credentials**가 필요합니다. 계정 로그인 이메일/비밀번호가 아닙니다. 지원되는 서버 주소는 NordVPN 공식 지원 문서에서 현재 목록을 확인합니다.

`input/network.env`는 Git ignore 대상입니다. 실제 자격 증명을 커밋하지 마십시오.

## 자동 실행

```bat
scripts\launch_desktop.bat
```

프록시가 활성화되어 있으면 실행 순서는 다음과 같습니다.

1. `desktop.app_launcher`가 `network.env` 검증
2. `127.0.0.1:<port>`에 이미 SOCKS endpoint가 없으면 `desktop.socks_bridge` 시작
3. 기존 FastAPI backend 시작
4. Chrome/Edge를 Catalogue Manager 전용 `--user-data-dir`로 시작
5. 해당 브라우저 프로세스에만 `--proxy-server=socks5://127.0.0.1:<port>` 추가
6. Pybooru는 `proxies={http, https}`에 `socks5h://127.0.0.1:<port>`를 명시
7. 앱 창 종료 시 앱이 시작한 SOCKS bridge 종료

## 왜 시스템 네트워크가 바뀌지 않는가

이 구현은 다음 작업을 하지 않습니다.

- Windows VPN 연결 생성/변경
- Windows 시스템 프록시 변경
- WinINET/WinHTTP proxy 변경
- 라우팅 테이블 변경
- TUN/TAP/Wintun 장치 생성
- DNS 서버 설정 변경

Chrome/Edge에는 해당 앱 프로세스의 command-line proxy만 전달합니다. Pybooru에는 해당 HTTP client의 `proxies` 인자만 전달합니다.

또한 FastAPI GUI 주소인 `127.0.0.1`은 Chromium의 implicit loopback proxy bypass 대상이므로 UI 자체는 proxy를 경유하지 않습니다.

## 한 번에 검증

설정 후 다음을 실행합니다.

```bat
scripts\test_app_proxy.bat
```

정상 예시:

```text
[probe] direct : <현재 회선 IP> (KR)
[probe] proxy  : <upstream 출구 IP> (US/NL/SE/...)
[probe] Danbooru via proxy: HTTP 200
[probe] OK: app proxy has a different public exit IP; system networking was not modified.
```

이 검사는 같은 Python 프로세스에서 `trust_env=False` direct session과 명시적 SOCKS proxy session을 각각 만들어 비교합니다. 시스템 프록시 설정을 변경하지 않습니다.

## 브라우저 검증

`launch_desktop.bat`으로 앱을 실행한 뒤 Catalogue Manager 안의 Danbooru Posts/Wiki 링크 또는 지역 제한 대상 페이지를 엽니다.

확인 기준:

- Catalogue Manager 전용 브라우저: proxy 국가 IP로 접속
- 일반 브라우저: 기존 회선 IP 유지
- 앱 UI `127.0.0.1`: 정상 로드
- Danbooru 수집/API: 정상 동작

## 제한

- 실제 지역 제한 해제 여부는 upstream proxy의 실제 출구 국가와 대상 사이트의 판정 방식에 달려 있습니다.
- NordVPN이 현재 제공하는 SOCKS5 국가에 원하는 지역이 없다면 다른 SOCKS5 provider 또는 해당 지역 VPS/SSH SOCKS endpoint를 사용해야 합니다.
- 이 방식은 VPN 드라이버 기반 전체 터널이 아닙니다. 지역 IP가 필요한 HTTP(S)/TCP 앱 트래픽 분리에 목적이 있습니다.
- `launch_app.bat` 개발 모드는 proxy bridge를 자동 시작하지 않습니다. 개발 모드에서 proxy가 필요하면 별도 터미널에서 `python -m desktop.socks_bridge`를 먼저 실행하십시오.
