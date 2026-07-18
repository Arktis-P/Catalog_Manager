# F4: 병합 상태 API + 추천 후보 개선 (담당: sonnet 5)

기준: `docs/PLAN_IMAGE_REVIEW_V2_FOLLOWUP.md` §2.7(백엔드), §4 전체.

## 범위 (이 파일들만)

- 수정: `backend/app/services/character_link_service.py` (추천 점수·정규화)
- 수정: `backend/app/services/review_service.py`, `backend/app/schemas/review.py` (V2 응답에 병합 상태 필드)
- 필요시: `backend/app/routers/character_catalog.py`의 parent 후보 API (검색 문자열 전달 확인·수정)
- 신규/수정: `backend/tests/test_character_link_recommend.py` (신규), 기존 관련 테스트 갱신
- 금지: v2_generation_pipeline.py, identity_checker.py, character_image_service.py, frontend/, docs/ (다른 작업자 동시 작업 중)

## 1. V2 응답 병합 상태 필드 (§2.7)

`V2ReviewCharacterResponse`(schemas/review.py)에 추가하고 review_service.py에서 채워라:

- `is_alternative: bool` (parent_character_id 존재)
- `parent_character_id: int | null`
- `parent_character_tag: str | null`
- `parent_display_name: str | null`
- `child_count: int` (N+1 쿼리 금지 — 목록 조회 시 집계 쿼리로)

## 2. 추천 후보 점수·정규화 (§4)

### 문제 재현 케이스 (테스트 필수)

- `murasaki_shion_(1st_costume)` 의 상위 후보 1순위 → `murasaki_shion`
- `ceres_fauna_(1st_costume)` 의 상위 후보 1순위 → `ceres_fauna`
- 현재는 무관한 `gawr_gura`가 추천되는 문제가 있음

### 태그 정규화

괄호 suffix 제거로 기본 태그 추출: `murasaki_shion_(1st_costume)` → `murasaki_shion`.
일반 suffix: costume, outfit, alternate_costume, 1st/2nd/3rd_costume, school_uniform, swimsuit, alter 등 — 괄호 안 내용 전체 제거를 기본으로 하되, `(genshin_impact)` 같은 시리즈 구분 괄호도 있으므로: **괄호 제거 후 기본 태그가 실제 다른 GlobalCharacter로 존재하는 경우에만** 정규화 매치로 취급.

### 점수 우선순위 (§4.3)

1. 정규화 후 기본 태그 완전 일치 (최우선, 압도적 가중치)
2. 동일 시리즈 소속 (CharacterSeriesLink 교집합)
3. 태그 prefix/핵심 토큰 일치 (기존 `similarity_score` 활용·개선)
4. 표시명 유사도
5. 포스트 수 (동점 시에만)

기존 `_rank_recommendations`를 이 기준으로 재작성. `similarity_score` 함수 자체의 시그니처는 유지(다른 곳에서 사용).

### 안전장치

- 유사도가 매우 낮으면(임계값) 추천 목록에서 제외 — 자동 선택 후보 없음으로 반환
- 추천 근거 문자열 필드 추가 (예: `match_reason: "base_tag_match" | "same_series" | "name_similarity"`) — 후보 응답 스키마에 포함 (UI 표시용)
- 후보 API가 검색어를 제대로 전달·사용하는지 확인하고 고쳐라 (§4.2)

## 완료 기준

- 위 두 회귀 케이스 포함 신규 테스트 통과
- `cd backend && ../.venv/Scripts/python.exe -m pytest tests/ -q` 기존 실패 3건(test_db_write_queue, test_series_merge_service, test_wiki_and_membership) 외 통과 (다른 작업자 영역 테스트가 일시 실패하면 무시하고 보고에 명시)
- 참고: test_series_merge_service의 기존 실패가 similarity_score 관련이면 이번 기회에 원인 확인 후 고쳐도 좋다 (선택)
- 커밋 금지, 스코프 밖 파일 수정 금지
