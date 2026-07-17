# WP8: 검증 배치·통계 (담당: gpt 5.5, 리포트 교차 검증: gemini)

기준: `docs/PLAN_IMAGE_GENERATION_REVIEW_V2.md` §15(5단계), §16.
선행: WP1~WP7 전체.

## 착수 전 필독 파일

- `backend/app/services/v2_generation_pipeline.py` (WP5 산출물)
- `backend/app/services/tag_relevance_service.py`, `relevance_collect_job_manager.py`
- `backend/app/routers/review.py`의 `/v2/stats`

## 범위

- 신규: `backend/scripts/v2_validation_batch.py` (CLI 스크립트)
- 신규: `backend/scripts/v2_validation_report.py`
- 필요시: stats API 보강 (`backend/app/routers/review.py` 최소 수정 허용)
- 스코프 밖: 파이프라인·검사기 로직 변경, 프론트엔드

## 기능 요구

### 1. 검증 배치 스크립트

- post_count 상위 N명(기본 500) 캐릭터 선택 (옵션: 시리즈·범위 지정)
- 실행 단계: 관련도 수집 → base_prompt 생성 → V2 생성 파이프라인 (각 단계 개별 실행/재개 가능, `--skip-*` 옵션)
- 중단·재개 안전: 이미 처리된 캐릭터는 건너뜀
- 진행 로그와 요약(성공/실패/스킵) 출력

### 2. 통계 리포트

수집·출력 항목:

- quality_status / identity_status 분포
- generation_status 분포 (generation_failed, likely_untrained 비율)
- 자동 재생성 횟수 분포·성공률 (quality 재시도, identity 보정 레벨별)
- 프롬프트 보정 성공(승격) 건수·레벨 분포
- primary_hair_needs_review 비율
- multicolor 추천 발생 비율
- 출력: 콘솔 표 + JSON 파일 (`data/exports/v2_validation_report.json`)

### 3. 오탐/미탐 기록 지원

- 리뷰에서 사람이 매긴 레이팅·완료 데이터와 자동 판정을 대조하는 기반 쿼리 함수 (예: quality_reject였지만 리뷰에서 3+ 레이팅을 받은 이미지 수)
- 임계값 조정 시 재판정 시뮬레이션까지는 범위 밖 — 카운트만

## 완료 기준

- 실 API 호출 없이 dry-run 모드 동작 (`--dry-run`: 대상 선정·계획만 출력)
- `cd backend && ../.venv/Scripts/python.exe -m pytest tests/ -q` 기존 실패 3건 외 통과 (스크립트는 import 가능해야 함)
- 커밋 금지, 스코프 밖 파일 수정 금지
