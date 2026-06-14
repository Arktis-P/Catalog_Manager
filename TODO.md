# Catalogue Manager — TODO

Danbooru 기반 캐릭터 이미지 카탈로그 관리 앱의 진행 목록입니다.  
이 프로젝트는 단기 MVP가 아니라, 최종적으로 **데스크톱 GUI 앱** 형태로 사용하는 것을 목표로 합니다.

---

## 완료됨

- [x] 프로젝트 폴더 구조 설계
- [x] SQLite DB 스키마 (series, characters, generation_jobs, images, reviews, settings)
- [x] FastAPI backend 기본 구조
- [x] React frontend 기본 구조 (Catalog / Review / Series / Generation 탭)
- [x] Series Manager (CRUD, CSV import/export, status 관리)
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

- [x] Danbooru API 연동 (pybooru)
- [x] series.csv / DB series 기준 캐릭터 tag 수집 CLI/API
- [x] character_tag + series_tag 중복 제외 저장
- [x] series+character 조합 post_count 수집
- [ ] 시리즈 위키 페이지 수집
- [ ] `list_of_*_characters` 페이지 자동 탐색
- [x] post 기반 character 후보 수집 (tag_string_character + 패턴 보조)
- [ ] wiki / related tags 기반 character 후보 수집
- [ ] character tag category 필터 및 alias/deprecated 처리
- [x] character_tag + series_tag 기준 중복 제거
- [x] 외형 태그 추출 (hair_color, multi_color_hair, hair_shape, eye_color, feature_tags)
- [x] Series 화면에 "Collect Characters" / "Appearance" 작업 버튼 추가
- [x] 수집 진행 상태 표시 (GlobalTaskBar, collecting / queued)
- [x] Catalog에 수집된 캐릭터 반영 (수집 즉시 Catalog API 노출)

---

## Phase 2 — Image Generator Connector

- [ ] character 생성 대상 선택 UI
- [ ] prompt_core 생성 규칙 구현 (Level 1~5)
- [ ] artist_combo_tags / negative_prompt 템플릿 연동
- [ ] NAIA queue 파일 export (`output/naia_queues/`)
- [ ] output 파일명 규칙 생성
- [ ] generation_jobs 상태 관리
- [ ] NAIA output 폴더에서 생성 결과 import
- [ ] images 테이블 생성 및 연결
- [ ] Generation 화면 구현

---

## Phase 3 — Review Tool

- [ ] 캐릭터 1명 단위 검수 UI
- [ ] 생성 이미지 2~4장 표시
- [ ] 대표 이미지(cover) 선택
- [ ] gender / type / rating / final_tags 입력
- [ ] 단축키 (1~4, X, F, M, N, U, R, 0~6, Enter, O)
- [ ] reviews 테이블 저장
- [ ] completed 처리 및 catalog_status 갱신
- [ ] Catalog → Review 이동 연결

---

## Phase 4 — Catalog Viewer 완성

- [ ] cover_image 표시 (로컬 경로 / 정적 파일 서빙)
- [x] Catalog API/UI 페이지네이션 (48건/페이지)
- [ ] Catalog 가상 스크롤 (수십만 건 DOM 렌더링 최적화)
- [ ] 필터 전체 구현 (rating, gender, type, hair_color, eye_color, feature_tags)
- [ ] prompt 복사
- [ ] status별 그룹/뱃지 UX 개선
- [ ] Regenerate 요청 연결
- [ ] 최종 catalog CSV export (`output/exports/`)

---

## Phase 5 — Image Auto Checker / Regeneration

- [ ] 생성 이미지 import 및 파일명 파싱
- [ ] 이미지 무결성 / 해상도 / blank / duplicate 검사
- [ ] 자동 태깅 연동 (placeholder → 실제 모델)
- [ ] hair_match / eye_match / gender_pred / solo 검사
- [ ] auto_status (pass / warning / reject_candidate)
- [ ] cover_score 계산
- [ ] needs_regen queue 및 보조 prompt level 자동 적용
- [ ] reject_candidate는 삭제하지 않고 Review에서 확인 가능하게 유지

---

## Phase 6 — Settings & 운영

- [x] Settings 화면 — Danbooru 동시 작업 수 (1~5, 캐릭터 수집/외형 추출 공유)
- [ ] tag dictionary / prompt template 편집
- [ ] Danbooru API key / rate limit 설정
- [ ] NAIA 경로 / output 경로 설정
- [ ] artist_combo_tags 관리

---

## Phase 7 — Desktop GUI 앱화

- [x] pywebview + WebView2 데스크톱 셀 (`desktop/launcher.py`)
- [x] production 빌드: frontend dist + backend 단일 포트 서빙
- [x] 백엔드 subprocess 자동 기동 및 창 닫을 때 종료
- [x] `scripts/launch_desktop.bat`, `Launch Catalogue Manager.vbs`
- [ ] 앱 아이콘 / 트레이 아이콘
- [ ] 설치형 배포 패키지 (exe / installer)
- [ ] (선택) Tauri/Electron으로 배포 패키지만 교체

---

## Phase 8 — 품질 / 유지보수

- [ ] API 단위 테스트
- [ ] 수집/생성 파이프라인 통합 테스트
- [ ] 에러 로깅 및 작업 이력
- [ ] 대량 데이터 성능 점검
- [ ] 문서화 (사용자 가이드, 데이터 포맷 설명)

---

## 설계 원칙 (유지)

1. Catalog Viewer를 메인 허브로 유지
2. Review Tool은 대량 검수용 집중 모드
3. 사용자 초기 입력은 `series.csv` 중심
4. NAIA는 외부 프로그램, 앱은 queue export / image import 담당
5. image 단위 상태와 character 단위 상태 분리
6. 자동 검수는 사람 검수를 보조하는 용도
