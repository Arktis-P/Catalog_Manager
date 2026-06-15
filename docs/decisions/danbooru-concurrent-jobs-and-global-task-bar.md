# Danbooru 백그라운드 작업 큐, 동시 실행 제한, GlobalTaskBar 고정 UI

| 항목 | 내용 |
|------|------|
| 결정일 | 2026-06-14 |
| 상태 | 적용됨 |
| 관련 코드 | `backend/app/services/collect_job_manager.py`, `backend/app/services/settings_service.py`, `frontend/src/context/CollectJobContext.tsx`, `frontend/src/components/GlobalTaskBar.tsx`, `frontend/src/components/Layout.tsx` |
| 관련 일지 | [docs/2026-06-14.md](../2026-06-14.md) |

---

## 배경

Catalogue Manager는 Series 탭에서 **캐릭터 Collect**와 **Appearance 추출**을 시리즈 단위로 백그라운드 job으로 실행한다. 두 작업 모두 Danbooru API(`posts`, `related_tag`, `counts` 등)를 반복 호출하며, 특히 Appearance는 시리즈당 수백~수천 번의 `related_tag` 요청이 발생할 수 있다.

초기 구현에서는 Series Collect를 요청할 때마다 즉시 스레드를 시작했고, 진행 UI는 Series 페이지에 가깝게 두었다. 이 방식의 문제는 다음과 같았다.

1. **여러 시리즈를 연속 요청**하면 Danbooru API 호출이 겹쳐 rate limit·HTTP 500이 발생하기 쉽다 (`kantai_collection` 등 대형 시리즈에서 확인).
2. **탭을 Series에서 Catalog 등으로 옮기면** 진행 표시를 놓치거나, 페이지마다 상태를 중복 관리해야 한다.
3. Collect와 Appearance를 **각각 무제한 병렬**로 돌릴지, **공통 한도**로 묶을지 정책이 없었다.

데스크톱 앱으로 오래 켜 두고 여러 시리즈를 큐에 넣는 사용 패턴을 전제로, **전역 동시 실행 상한 + FIFO 대기열 + 어디서든 보이는 컴팩트 진행 UI**가 필요했다.

---

## 선택지

### A. 동시 실행 제한

| 옵션 | 설명 |
|------|------|
| A1. 제한 없음 | 요청마다 즉시 스레드 시작 (초기 방식) |
| A2. 시리즈 타입별 독립 상한 | Collect max N, Appearance max M |
| A3. **전역 공유 상한** | Collect·Appearance가 **같은 슬롯 풀**을 나눠 씀 |
| A4. 순차만 허용 | 동시 1개 고정 |

### B. 상한 값과 변경 방법

| 옵션 | 설명 |
|------|------|
| B1. 코드/환경변수 고정 | `config.py` 또는 `.env`만 |
| B2. **Settings UI + DB 저장** | 앱 내에서 1~5 조정, 재시작 없이 dispatch에 반영 |
| B3. 요청마다 사용자 입력 | Series마다 동시 개수 지정 |

### C. 진행 UI 위치·형태

| 옵션 | 설명 |
|------|------|
| C1. Series 페이지 전용 패널 | 탭 이탈 시 사라짐 |
| C2. **Layout 전역 + React Context** | 모든 탭에서 동일 job 상태 |
| C3. OS 알림만 | Windows toast 등 (보조 수단으로는 유지) |

### D. 상단 고정(sticky)

| 옵션 | 설명 |
|------|------|
| D1. 페이지 스크롤과 함께 이동 | 긴 Series 테이블에서 진행 바가 화면 밖으로 |
| D2. **`app-top` sticky** | 네비 + GlobalTaskBar를 한 덩어리로 상단 고정 |
| D3. 플로팅 오버레이 | 화면 모서리 위젯 |

---

## 결정

### 1. Danbooru 백그라운드 작업 — 전역 FIFO 큐 + 공유 동시 실행 상한

- `SeriesJobManager`(기존 `CollectJobManager` 확장)가 **모든 Danbooru 백그라운드 job**을 관리한다.
- job 종류: `character_collect`, `appearance_extract` (동일 큐·동일 슬롯).
- **기본 동시 실행: 2개.** 실행 중 job이 상한 미만이면 큐에서 FIFO로 꺼내 시작한다.
- **시리즈당 active job 1개**: 같은 `series_id`에 `queued`/`running` job이 있으면 새 요청은 기존 job을 반환(중복 방지).
- 완료·실패 시 `_dispatch_next()`로 빈 슬롯에 다음 job 자동 시작.

### 2. 동시 개수 — Settings에서 1~5로 조정

- DB `settings` 테이블 키: `danbooru_collect_max_concurrent`.
- 기본값: `config.py`의 `danbooru_collect_max_concurrent = 2` (DB 값 없을 때 fallback).
- Settings 탭 슬라이더: **1~5**, 저장 시 즉시 `series_job_manager.set_max_concurrent()`로 대기 job dispatch 재시도.
- **Collect와 Appearance를 합산**한 Danbooru 동시 작업 수로 해석한다 (별도 상한 없음).

### 3. 진행 UI — GlobalTaskBar + CollectJobContext

- `CollectJobProvider`가 job 목록·폴링(800ms)·완료 알림을 전역 관리.
- `GlobalTaskBar`가 `queued` / `running` / `completed` / `failed` job을 **컴팩트 한 줄 패널**로 표시.
- job 타입 배지: Collect vs Appearance.
- 완료·실패 job은 Dismiss 가능; running job은 탭과 무관하게 상단에 유지.

### 4. 레이아웃 — `app-top` sticky

- `Layout`에서 **헤더(네비) + GlobalTaskBar**를 `app-top`으로 묶고 `position: sticky; top: 0` 적용.
- 페이지 본문(`Outlet`) 스croll과 분리되어, Catalog·Review·Series 어디에서든 진행 상태가 보인다.
- 높이를 줄인 컴팩트 패널(얇은 progress bar, ellipsis 메시지)로 sticky 영역이 본문을 과도하게 가리지 않게 했다.

---

## 이유

### 동시 2개(기본) + 공유 큐

- pybooru/Danbooru는 job마다 독립 `DanbooruClient`·요청 delay를 두지만 **job 간 rate limiter는 없음**. 병렬 job 수 = API 부하 배수.
- Collect만 2개、Appearance만 2개처럼 나누면 총 4가 될 수 있어, **하나의 풀**로 묶는 편이 rate limit 관리에 유리하다.
- 2는 “너무 느리지 않으면서 500 빈도를 줄이는” 실용적 기본값으로 대화 중 합의했다.
- FIFO는 사용자가 Series 탭에서 연속 클릭한 **선입선출** 기대와 일치한다.

### Settings 1~5

- power user가 환경·계정 등급에 맞게 조정할 여지를 주되, **5 상한**으로 Danbooru 남용·자기 차단 위험을 제한.
- env만 쓰면 데스크톱 사용자가 `.env`를 고치기 어렵다. Phase 6 Settings 방향과도 맞다.
- dispatch 시점마다 DB에서 상한을 읽어 **저장 직후** 큐에 반영 가능 (재시작 불필요).

### GlobalTaskBar + sticky

- Collect/Appearance는 **수 분~수십 분** job이다. 사용자는 진행 중 **다른 탭에서 Catalog·Review**를 본다.
- Series 페이지에만 UI를 두면 “백그라운드” 의미가 약해진다.
- sticky는 모달/플로ating보다 **데스크톱 앱 네비 패턴**과 맞고, WebView2에서 구현이 단순하다.
- Windows 알림(`showTaskCompleteNotification`)은 **완료/실패 보조**로 유지하고, 진행 중 피드백의 주 채널은 상단 바로 통일했다.

---

## 한계

| 한계 | 설명 |
|------|------|
| API rate limit | 동시 2~5로도 대형 시리즈·연속 Appearance 시 500 가능. `danbooru_request_delay`·재시도는 별도 정책. |
| job 간 우선순위 없음 | Collect vs Appearance FIFO만; “Collect 먼저” 같은 타입 우선순위 없음. |
| 시리즈당 1 job | 같은 시리즈에서 Collect 완료 직후 Appearance를 큐에 넣는 건 가능하나, **동시에** 두 job 불가. |
| 메모리 내 job 이력 | job 상태는 프로세스 메모리; 앱 재시작 시 큐·진행 소실. DB job 테이블 없음. |
| 목록 상한 | `list_visible_jobs(limit=20)` — 오래된 completed job은 UI에서만 dismiss로 정리. |
| 설정 범위 | `danbooru_request_delay`는 Settings에 **표시만** 하고 UI 편집은 미구현 (env/config). |
| sticky 높이 | job이 많으면 상단 바가 여러 줄로 늘어날 수 있음 (현재는 컴팩트 완화). |

---

## 재검토 조건

다음 상황이면 이 결정을 다시 검토한다.

1. **Danbooru 500/rate limit이 Settings 1~2에서도 지속**  
   → 전역 `request_delay` UI, job 타입별 상한(A2), 또는 Appearance 전용 야간 배치 큐 검토.

2. **Generation Connector 등 Phase 2 job 추가**  
   → Danbooru job과 NAIA/로컬 job을 **같은 GlobalTaskBar**에 넣을지, 큐를 분리할지, `SeriesJobManager` rename/일반화 필요.

3. **앱 재시작 후 job 재개 요구**  
   → in-memory 큐 포기, `generation_jobs` 유사 테이블로 영속화.

4. **우선순위·사용자 큐 편집** (특정 시리즈 먼저, Appearance 보류 등)  
   → FIFO 단순 큐에서 우선순위 큐 또는 pause/resume API.

5. **sticky UI가 본문 가림**  
   → job 1줄 요약 + 클릭 시 펼치기, 또는 플로팅 미니바(D3)로 전환.

6. **동시 5가 Danbooru ToS/계정 제재와 충돌**  
   → 상한 하향 또는 Gold 등급별 권장값 문서화.

---

## 구현 요약 (참고)

```
[Series UI] Collect / Appearance 클릭
        ↓
POST .../collect/start  또는  .../appearance/start
        ↓
SeriesJobManager._enqueue → FIFO 큐
        ↓
_dispatch_next (running < settings.max_concurrent)
        ↓
스레드 → CharacterService / AppearanceService
        ↓
CollectJobContext 폴링 ← GET /api/characters/collect/jobs/{id}
        ↓
Layout.app-top → GlobalTaskBar (sticky)
```

**설정 경로:** Settings 탭 → `PATCH /api/settings` → `danbooru_collect_max_concurrent` (1~5).

---

## 관련하지 않은 것 (이 문서 범위 밖)

- Appearance/Catalog/Review 데이터 분리 (`appearance_confirmed` 등) — 별도 의사결정
- Danbooru 500 재시도 횟수 — reliability 튜닝
- `danbooru_request_delay` 편집 UI — 미구현
