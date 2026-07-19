# F19(1/2): 리뷰 일괄 완료 API (담당: sonnet 5, 백엔드 전용)

## 목표

레이팅이 매겨진 여러 캐릭터의 리뷰를 한 번의 요청으로 완료 처리하는 API. (프론트 버튼/단축키는 다음 라운드에서 다른 스펙으로 진행 — 이번엔 백엔드만.)

## 필독

- `backend/app/routers/review.py`의 `complete_v2_review_character`(~205행), `save_v2_review_character` 서비스 호출부
- `backend/app/services/review_service.py`의 `save_v2_review_character`
- `backend/app/schemas/review.py`의 V2 스키마들

## 범위

- 수정: 위 3개 파일, 테스트 1개 신규(`backend/tests/`)
- 금지: frontend 전부, 그 외 backend. 실제 DB·output 수정 금지.

## 구현

`POST /review/v2/bulk-complete`:

- 요청: `{ items: [{ character_id, rating, gender?, base_prompt?, selected_tags?, cover_image_id? }] }` (1~100개)
- 항목별 처리 (개별 트랜잭션 아님 — 한 세션에서 순회, 항목 실패는 다른 항목에 영향 없게):
  - `rating`이 null이면 그 항목은 skip (결과에 skipped로 표기)
  - `cover_image_id` 미지정 시 **해당 캐릭터의 첫 번째 표시 이미지**(is_rejected 제외, 기존 정렬 규칙)로 저장
  - 성공 시 `review_status="completed"` (기존 `save_v2_review_character` 재사용)
- 응답: `{ completed: n, skipped: n, failed: n, results: [{character_id, status, error?}] }`

## 테스트

- 레이팅 있는 항목 완료 + cover 기본값(첫 이미지) 적용
- rating null → skipped
- 존재하지 않는 character_id → 해당 항목만 failed, 나머지 정상

## 완료 기준

- 테스트 실행이 차단되면 실행 생략을 보고에 명시 (오케스트레이터가 실행)
- git commit 금지, 간결한 보고
