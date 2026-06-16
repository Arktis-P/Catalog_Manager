# Catalogue Manager — TODO

Danbooru 기반 캐릭터 이미지 카탈로그 관리 앱의 진행 목록입니다.  
최종 목표는 **데스크톱 GUI 앱** 형태로 일상적으로 사용하는 것입니다.

---

## 현재 상태 (2026-06)

**핵심 플로우 완료:** 수집 → 외형 확인 → 이미지 생성 → Review 선별 → Catalog 탐색·수정

| 단계 | 상태 |
|------|------|
| Phase 1 Character Collector | ✅ 실사용 가능 (일부 정리 도구 미완) |
| Phase 2 Image Generator | ✅ 완료 |
| Phase 3 Review Tool | ✅ 완료 |
| Phase 4 Catalog Viewer | ✅ 완료 |
| Phase 5~8 | ⏸ 보류 — 아래 우선순위 참고, 필요할 때만 진행 |

**당장 할 일:** 실제 시리즈로 end-to-end 돌려보며, 막히는 부분만 수정.

---

## 완료됨

- [x] 프로젝트 폴더 구조 설계
- [x] SQLite DB 스키마 (series, characters, generation_jobs, images, reviews, settings)
- [x] FastAPI backend 기본 구조
- [x] React frontend 기본 구조 (Catalog / Review / Series / Generation 탭)
- [x] Series Manager (CRUD, CSV import/export, status 관리, 시리즈 병합)
- [x] Catalog Viewer 기본 화면 (카드, 필터, stats, Danbooru 링크)
- [x] input 폴더 샘플 (series.csv, tag_dictionaries, prompt_templates)
- [x] 가상환경 기반 실행 스크립트 (setup / launch)
- [x] Git 기본 세팅
- [x] Danbooru API key 설정 (`input/danbooru.env`)
- [x] Copyright tag → `series.csv` 수집 스크립트
- [x] Desktop shell: pywebview + WebView2 (창 닫기 = backend 종료)
- [x] production 단일 포트 GUI 서빙 (FastAPI + React dist)
- [x] Catalog API SQL 페이지네이션 (대량 데이터 대비)
- [x] Catalog UI 페이지네이션 (48건/페이지)

---

## Phase 1 — Character Collector

### 수집·외형 파이프라인

- [x] Danbooru API 연동 (pybooru)
- [x] series.csv / DB series 기준 캐릭터 tag 수집 CLI/API
- [x] character_tag + series_tag 중복 제외 저장
- [x] series+character 조합 post_count 수집
- [x] post 기반 character 후보 수집 (tag_string_character + 패턴 보조)
- [x] character_tag + series_tag 기준 중복 제거
- [x] **위키 / `list_of_*_characters` 기반 캐릭터 수집** (Danbooru `wiki_pages.json`, DText 링크 파싱)
- [x] **하위 시리즈 hub**: 위키 copyright 링크 → DB 시리즈 매칭 → 수집 → 상위 병합
- [x] **위키 실패 시 legacy fallback** (post 스캔 + 패턴, `used_legacy_fallback` 플래그)
- [x] 외형 태그 추출 (hair_color, multi_color_hair, hair_shape, eye_color, feature_tags, gender)
- [x] gender 규칙: `1girl` / `1boy` / `no_humans` 만 저장 (연관 태그 빈도 비교)
- [x] **`related tags` copyright 기반 시리즈 소속 검증** → `needs_check` + 사유 저장
- [x] `generation_prompt` 생성 (`{{character, [[hair…]]}}`)
- [x] Series 화면에 Collect / Appearance / Characters / Merge 버튼
- [x] 수집·외형 추출 공유 FIFO 작업 큐 + Settings 동시 실행 수 (1~5)
- [x] GlobalTaskBar (상단 고정 진행 UI, Collect / Appearance 구분)
- [x] Catalog에 수집된 캐릭터 반영 (수집 즉시 Catalog API 노출)
- [x] 미확정 외형 태그 Catalog 마스킹 + Review 탭에서 Confirm 후 반영
- [x] 시리즈 status UI (`collected` / `tagged` 등 배지 1개 표시)
- [x] Danbooru 500/429 재시도

### 캐릭터 목록·병합

- [x] 시리즈별 Characters 팝업 (수집 출처, 외형 태그, gender 표 형식)
- [x] Characters 팝업 **`needs_check` status 필터**
- [x] 전체/시리즈별 캐릭터 CSV export
- [x] 시리즈 병합 (collected/tagged → 상위/하위 계층, 중복 캐릭터는 상위 우선)
- [x] 병합 UI: 유사 시리즈 후보, preview, 진행 표시줄, Unmerge
- [x] 병합 캐릭터 `source_series_id` 추적 및 Characters 팝업 `source_series` 컬럼
- [x] **`reset_catalog.py --skip-series-import`**: 시리즈 유지·캐릭터/이미지/pending_review 초기화·병합 관계 해제

### Phase 1 잔여 (선택 — P1)

- [ ] character tag **alias/deprecated** 정규화
- [ ] `needs_check` **일괄 삭제 / 시리즈 이동** API (membership 사유 대상) — *Review에서 개별 처리는 가능*
- [ ] affiliation ratio (`count(char+series)/count(char)`) 자동 플래그
- [ ] wiki/list 출처(`from_list_page`)만 생성 허용 옵션

---

## Phase 2 — Image Generator Connector

- [x] character 생성 대상 선택 UI
- [x] prompt_core 생성 규칙 구현 (Level 1~5)
- [x] artist_combo_tags / negative_prompt 템플릿 연동
- [x] prefix / suffix 분리 (와일드카드 앞·뒤, Settings에서 편집)
- [x] 캐릭터당 기본 2장 생성 (`generation_images_per_character`)
- [x] 생성 직후 자동 검사 (WD14 태그 confidence, 눈/손 디테일)
- [x] NAIA queue 파일 export (`output/naia_queues/`)
- [x] output 파일명 규칙 생성
- [x] generation_jobs 상태 관리
- [x] NAIA API로 생성 결과 import → `output/generated_images/pending_review/`
- [x] images 테이블 생성 및 연결
- [x] Generation 화면 구현
- [x] **Generation: `needs_check` 기본 제외 + 검토 전용 필터** (needs_check 모드에서 생성 비활성)

---

## Phase 3 — Review Tool

### Appearance (기존)
- [x] 외형 태그 Review 기본 (draft 목록 + Confirm → Catalog 반영)
- [x] 시리즈 필터 · 인라인 태그 편집

### Catalog Review (핵심)
- [x] 서브탭 분리 (Appearance / Catalog Review)
- [x] 시리즈 필터
- [x] 3단 행 UI (이미지×2 + 정보 패널)
- [x] 가상 스크롤 · lazy load
- [x] 커버 선택 · Complete → reviews 저장
- [x] gender 색상 (1girl 분홍 / 1boy 하늘색)
- [x] 외형 태그 프롬프트 토글 (hair/multi/eyes/features)
- [x] rating 입력 (0~6, -1)
- [x] Danbooru Posts / Wiki 링크
- [x] 단축키 (방향키, 0~6/-, Enter, g/b/n, r, Ctrl+Z, q/w)
- [x] Regenerate 연동 (단일 캐릭터)
- [x] needs_check 검토 UI (사유, 삭제/이동)
- [x] Catalog → Review 딥링크
- [x] 재생성 이미지 3~4장 UI 확장
- [x] 썸네일 API · 메모리 상한 Settings

---

## Phase 4 — Catalog Viewer 완성

- [x] cover_image 표시 (로컬 경로 / 정적 파일 서빙)
- [x] Catalog API/UI 페이지네이션 (48건/페이지)
- [x] Catalog 가상 스크롤 (수십만 건 DOM 렌더링 최적화)
- [x] 필터 전체 구현 (rating, gender, type, hair_color, eye_color, feature_tags)
- [x] prompt 복사
- [x] status별 그룹/뱃지 UX 개선
- [x] Regenerate 요청 연결
- [x] 최종 catalog CSV export (`output/exports/`)
- [x] 랜덤 캐릭터 (rating 가중치 기반, 가중치 Settings화는 추후)
- [x] 카탈로그 인라인 수정 (appearance + review 필드)

---

## 이후 작업 우선순위

Phase 5 이후는 **플로우 완성에 필수가 아님**. 실사용 중 불편함·규모·배포 필요가 생길 때 골라서 진행.

| 우선순위 | 범위 | 언제 하면 좋은지 |
|---------|------|-----------------|
| **P0** | 실사용 + 버그/UX 핫픽스 | 지금. 막히는 것만 고침 |
| **P1** | Phase 1 잔여 (`needs_check` 일괄 정리 등) | `needs_check`가 많이 쌓여 Review/Catalog가 지칠 때 |
| **P2** | Phase 4 보완 (랜덤 가중치 Settings UI 등) | Catalog 랜덤·필터를 자주 쓸 때 |
| **P3** | Phase 5 자동 검수 강화 | 생성량이 많아 Review 부담이 클 때 |
| **P4** | Phase 6 Settings 잔여 | `danbooru.env` / 파일 직접 편집이 불편할 때 |
| **P5** | Phase 7 installer / 배포 패키지 | 다른 PC에 설치·배포할 때 |
| **P6** | Phase 8 테스트·로깅·문서 | 장기 운영·데이터 대량화·협업 시 |

### P1 — 데이터 정리 (Phase 1 잔여)

- [ ] `needs_check` 일괄 삭제 / 시리즈 이동 API
- [ ] character tag alias/deprecated 정규화
- [ ] affiliation ratio 자동 플래그
- [ ] wiki/list 출처만 생성 허용 옵션

### P2 — Catalog 보완 (Phase 4)

- [ ] 랜덤 캐릭터 rating 가중치 Settings UI

### P3 — 자동 검수 보조 (Phase 5, 선택)

- [x] 생성 이미지 import 시 자동 검사 실행
- [x] 자동 태깅 연동 (WD14 ONNX)
- [x] auto_status · cover_score (기본)
- [ ] 이미지 무결성 / 해상도 / blank / duplicate 검사
- [ ] hair_match / eye_match / gender_pred / solo 검사
- [ ] needs_regen queue 및 보조 prompt level 자동 적용
- [ ] reject_candidate Review 확인 UX 정리

### P4 — Settings 잔여 (Phase 6, 선택)

- [x] Danbooru 동시 작업 수 · generation prompt · Review 썸네일
- [ ] Danbooru API key / rate limit / fallback 플래그 UI
- [ ] artist_combo_tags 관리 UI

### P5 — 배포 (Phase 7, 선택)

- [x] pywebview 데스크톱 실행 · production 빌드 · launch 스크립트 · 아이콘
- [ ] 설치형 배포 패키지 (exe / installer)
- [ ] (선택) Tauri/Electron 배포 패키지 교체

### P6 — 유지보수 (Phase 8, 선택)

- [ ] API 단위 테스트 (wiki 파서, membership 검증 등)
- [ ] 수집/생성 파이프라인 통합 테스트
- [ ] 에러 로깅 및 작업 이력
- [ ] 대량 데이터 성능 점검
- [ ] 사용자 가이드 · 데이터 포맷 문서
- [x] 개발 일지 · 의사결정 문서 (`docs/2026-06-15.md`, `docs/decisions/`)

---

## Phase 5~8 (레거시 참고 — 위 우선순위 섹션으로 통합)

<details>
<summary>원본 Phase 5~8 체크리스트 (접기)</summary>

### Phase 5 — Image Auto Checker / Regeneration

- [x] 생성 이미지 import 시 자동 검사 실행
- [ ] 이미지 무결성 / 해상도 / blank / duplicate 검사
- [x] 자동 태깅 연동 (WD14 ONNX, `input/models/wd14/` — 미설치 시 warning)
- [ ] hair_match / eye_match / gender_pred / solo 검사 (태그·디테일 일부 구현)
- [x] auto_status (pass / warning / reject_candidate)
- [x] cover_score 계산 (기본)
- [ ] needs_regen queue 및 보조 prompt level 자동 적용
- [ ] reject_candidate는 삭제하지 않고 Review에서 확인 가능하게 유지

### Phase 6 — Settings & 운영

- [x] Settings 화면 — Danbooru 동시 작업 수 (1~5, 캐릭터 수집/외형 추출 공유)
- [x] generation prompt prefix/suffix/negative 편집
- [x] Review 썸네일 크기 · 동시 로드 이미지 상한
- [ ] Danbooru API key / rate limit 설정 (위키/legacy fallback 플래그 UI 포함)
- [x] NAIA 경로 / output 경로 설정
- [ ] artist_combo_tags 관리

### Phase 7 — Desktop GUI 앱화

- [x] pywebview + WebView2 데스크톱 셀 (`desktop/launcher.py`)
- [x] production 빌드: frontend dist + backend 단일 포트 서빙
- [x] 백엔드 subprocess 자동 기동 및 창 닫을 때 종료
- [x] `scripts/launch_desktop.bat`, `Launch Catalogue Manager.vbs`
- [x] 앱 아이콘 (favicon, 데스크톱 창/작업 표시줄, `scripts/sync_app_icon.bat`)
- [ ] 설치형 배포 패키지 (exe / installer)
- [ ] (선택) Tauri/Electron으로 배포 패키지만 교체

### Phase 8 — 품질 / 유지보수

- [ ] API 단위 테스트 (wiki 파서, membership 검증 등)
- [ ] 수집/생성 파이프라인 통합 테스트
- [ ] 에러 로깅 및 작업 이력
- [ ] 대량 데이터 성능 점검
- [ ] 문서화 (사용자 가이드, 데이터 포맷 설명)
- [x] 개발 일지 · 의사결정 문서 (`docs/2026-06-15.md`, `docs/decisions/`)

</details>

---

## 설계 원칙 (유지)

1. Catalog Viewer를 메인 허브로 유지
2. Review Tool은 대량 검수용 집중 모드
3. 사용자 초기 입력은 `series.csv` 중심
4. NAIA는 외부 프로그램, 앱은 queue export / image import 담당
5. image 단위 상태와 character 단위 상태 분리
6. 자동 검수는 사람 검수를 보조하는 용도
7. **캐릭터 수집: 위키/list 우선, post 스캔은 fallback·보조**
8. **시리즈-캐릭터 확정: 자동 삭제보다 `needs_check` + 생성 게이트**
