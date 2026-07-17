# WP7: V2 리뷰 완료·1차 레이팅 API (담당: gpt 5.5)

기준: `docs/PLAN_IMAGE_GENERATION_REVIEW_V2.md` §11.4(필터), §12, §13.
선행: WP1 (review_status/rating_stage 컬럼), WP4 (quality/identity 필드 — 필터에 사용).

## 착수 전 필독 파일

- `backend/app/routers/review.py`, `backend/app/schemas/review.py`
- `backend/app/services/review_service.py`
- `backend/app/services/review_catalog_serializer.py` (WP4가 수정 중일 수 있음 — 충돌 최소화: 함수 추가 위주로)

## 범위

- 수정: `backend/app/routers/review.py`, `backend/app/schemas/review.py`, `backend/app/services/review_service.py`
- 신규: `backend/tests/test_v2_review_api.py`
- 스코프 밖: 프론트엔드, 검사기, Job

## 기능 요구

### 1. V2 리뷰 목록 API

`GET /api/review/v2/characters` (기존 리뷰 목록 API 패턴 준수):

- 캐릭터 중심 목록 + 임시 대표 이미지 + quality/identity 상태·사유 + 생성 상태 + first_post_at + 리뷰 상태·레이팅
- 필터 쿼리 파라미터 (§11.4 전체):
  - `review_status` (pending/in_progress/completed)
  - `rating` (특정 값 / `unrated`)
  - `quality_status`, `identity_status`
  - `generation_status` (generation_failed, likely_untrained 포함)
  - `gender`, `series_id`
  - `multicolor` (has/suggested)
  - `prompt_modified` (base_prompt != 초기 생성값, previous_base_prompt 존재 여부로 판단)
- 페이지네이션은 기존 목록 API 방식 재사용

### 2. V2 리뷰 완료 API

`POST /api/review/v2/characters/{id}/complete`:

- 저장: rating(-1~6), gender, base_prompt(수정 시 previous_base_prompt 이관), selected_tags, review_status='completed', rating_stage='primary'
- rating 유효값: -1,0,1,2,3,4,5,6 (4는 허용하되 응답에 비권장 플래그 불필요 — 프론트에서 안내)
- 부분 저장(중간 저장) API: review_status='in_progress'로 동일 필드 저장

### 3. 통계 API (선택 구현, 여유 있으면)

`GET /api/review/v2/stats`: 상태별 카운트 (리뷰 진행률 표시용)

## 테스트

- 필터 각각 + 조합 2~3개
- 완료 저장 → 재조회 검증, previous_base_prompt 이관 검증
- 잘못된 rating 값 422

## 완료 기준

- `cd backend && ../.venv/Scripts/python.exe -m pytest tests/ -q` 통과 (기존 실패 3건 무시)
- 커밋 금지, 스코프 밖 파일 수정 금지
