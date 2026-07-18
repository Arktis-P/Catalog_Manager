# F3: related tags 기반 관련도 후보 수집 (담당: gpt 5.5)

기준: `docs/PLAN_IMAGE_REVIEW_V2_FOLLOWUP.md` §2.2, §5 Phase 5.
선행: F1·F2 커밋 후 착수.

## 착수 전 필독

- `backend/app/services/tag_relevance_service.py` (수정 대상)
- `backend/app/integrations/danbooru/client.py`의 `get_related_tags` 및 `appearance_extractor.py`의 `parse_related_tags` (기존 재사용)
- `backend/app/services/appearance_service.py` (related tags 사용 예)

## 범위 (이 파일들만)

- 수정: `backend/app/services/tag_relevance_service.py`
- 수정: `backend/tests/test_tag_relevance_service.py`
- 금지: 그 외 전부 (특히 pipeline·checker·frontend)

## 변경 내용

### 1. 후보군 수집 변경

현재: 기존 외형 필드(hair_color 등) + whitelist 만 후보.
변경: **related tags API 응답을 우선 후보군으로 추가**:

- `collect_for_character`에서 `get_related_tags(character_tag)` 호출 → `parse_related_tags`로 파싱
- 결과 중 외형 카테고리(머리색/머리모양/multicolor/눈색/기타 외형)에 해당하는 태그만 필터해 후보에 합류 (기존 appearance_extractor의 색상·모양 분류 상수 재사용)
- 기존 외형 필드·whitelist 후보와 합집합, 중복 제거
- related tags 응답이 동시 등장 수를 제공하면 count API 호출을 절약하는 데 활용하되, 최종 relevance_score 계산 기준(동시 등장 ÷ 전체 포스트)은 유지 — 응답 값으로 대체 가능하면 대체하고 불가하면 기존 count_posts 호출 유지
- related tags 호출 실패 시 기존 방식으로 폴백 (수집이 막히면 안 됨)

### 2. 임계값·선정 로직 불변

기존 threshold/소표본 보정/대표 머리색 선정 로직은 변경하지 않는다. 후보군 소스만 확장.

## 테스트

- related tags mock 응답 → 외형 태그만 후보로 합류 검증
- related tags 실패 → 폴백 동작 검증
- 기존 테스트 전부 통과 유지

## 완료 기준

- `cd backend && ../.venv/Scripts/python.exe -m pytest tests/ -q` 기존 실패 3건 외 통과
- 커밋 금지, 스코프 밖 파일 수정 금지
