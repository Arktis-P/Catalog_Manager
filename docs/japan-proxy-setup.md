# Japan App-scoped Proxy Setup

Catalogue Manager의 Danbooru/Pybooru 요청과 전용 Chrome/Edge 외부 요청만 일본 IP로 보내기 위한 권장 구성입니다.

## 권장 구성

```text
Windows / 일반 앱 ------------------------------> 기존 회선
Catalogue Manager
  ├─ FastAPI 127.0.0.1 ------------------------> DIRECT
  ├─ Pybooru -----------------------------------> 127.0.0.1:1080
  └─ 전용 Chrome/Edge --------------------------> 127.0.0.1:1080
                                                   |
                                                   v
                                           Windows ssh.exe -D
                                                   |
                                                   v
                                             Tokyo Linux VPS
                                                   |
                                                   v
                                                Japan IP
```

앱은 Windows 시스템 VPN, 시스템 프록시, DNS, 라우팅 테이블을 변경하지 않습니다.

## 1. 일본 SSH 호스트 준비

권장 예시는 AWS Lightsail의 Asia Pacific (Tokyo) 리전 Linux 인스턴스입니다. 가장 작은 인스턴스로 충분합니다. SSH 접속 가능한 다른 일본 VPS가 이미 있다면 그것을 그대로 사용해도 됩니다.

고정된 출구 IP를 원하면 VPS에 static IP를 연결합니다.

필요한 로컬 정보는 세 가지뿐입니다.

- VPS public/static IP 또는 hostname
- SSH username (Ubuntu 이미지라면 일반적으로 `ubuntu`)
- SSH private key의 로컬 파일 경로

비밀키 내용 자체를 `network.env`에 넣지 않습니다. 파일 경로만 기록합니다.

## 2. Catalogue Manager 설정 파일 생성

```bat
scripts\setup_japan_proxy.bat
```

이 명령은 추적되지 않는 `input/network.env`를 만들고 메모장으로 엽니다.

다음 값만 채웁니다.

```dotenv
CATALOGUE_APP_PROXY_ENABLED=1
CATALOGUE_APP_PROXY_MODE=ssh
CATALOGUE_PROXY_EXPECTED_COUNTRY=JP
CATALOGUE_APP_PROXY_HOST=127.0.0.1
CATALOGUE_APP_PROXY_PORT=1080

CATALOGUE_PROXY_SSH_HOST=YOUR_JAPAN_HOST
CATALOGUE_PROXY_SSH_PORT=22
CATALOGUE_PROXY_SSH_USER=YOUR_SSH_USER
CATALOGUE_PROXY_SSH_KEY_FILE=YOUR_LOCAL_SSH_KEY_PATH
```

`input/network.env`는 Git ignore 대상입니다.

## 3. 자동 동작

```bat
scripts\launch_desktop.bat
```

프록시가 활성화되어 있으면 앱이 자동으로 다음과 같은 SSH dynamic forward를 실행합니다.

```text
ssh -N -D 127.0.0.1:1080 ... USER@JAPAN_HOST
```

실제 실행에는 key-only 인증, `ExitOnForwardFailure`, keepalive, changed-host-key 거부 설정이 추가됩니다.

그 뒤:

- Pybooru는 `socks5h://127.0.0.1:1080`을 명시적으로 사용
- Catalogue Manager 전용 Chrome/Edge는 `--proxy-server=socks5://127.0.0.1:1080` 사용
- localhost GUI는 direct
- 다른 Windows 앱은 영향 없음

## 4. 일본 IP 검증

```bat
scripts\test_app_proxy.bat
```

성공 조건:

```text
[probe] direct : <기존 회선 IP> (<기존 국가>)
[probe] proxy  : <Tokyo VPS IP> (JP)
[probe] expected proxy country: JP
[probe] Danbooru via proxy: HTTP 200
[probe] OK: ...
```

프록시 국가가 `JP`가 아니면 진단기는 실패 코드로 종료합니다.

## 5. 주의

- Windows에서 `ssh` 명령이 없으면 Windows OpenSSH Client를 활성화해야 합니다.
- VPS SSH port는 로컬 PC에서 접근 가능해야 합니다.
- VPS를 삭제하거나 static IP를 해제하면 `network.env`의 host를 갱신해야 합니다.
- VPS는 단순 SOCKS 출구이므로 별도의 웹 서버나 프록시 서버 프로그램 설치가 필요하지 않습니다.
