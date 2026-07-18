# F2: identity 검사 단순화·성능 개선 (담당: gpt 5.5)

기준: `docs/PLAN_IMAGE_REVIEW_V2_FOLLOWUP.md` §2.6.

## 범위 (이 파일들만)

- 수정: `backend/app/services/identity_checker.py`
- 수정: `backend/app/services/character_image_service.py` (known_character_tags 조회·전달 제거)
- 수정: `backend/tests/test_identity_checker.py`, `test_character_image_service_v2.py`
- 금지: v2_generation_pipeline.py (다른 작업자가 동시 수정 중 — 절대 건드리지 마라), quality_checker.py, frontend/, docs/

## 변경 내용

### 1. 전체 캐릭터 전수 비교 제거

- `character_image_service.py`의 `known_character_tags` DB 전체 조회(약 170행)를 제거
- `identity_checker.py`의 `known_character_tags` 파라미터는 **하위 호환을 위해 시그니처에 유지하되 기본값 `()` 그대로, 내부에서 전수 비교 용도로 사용하지 않는다**
- 대신: WD 태거 출력에서 **character 카테고리 태그 중 자기 태그가 아닌 고신뢰(기존 임계값) 태그**를 충돌 후보로 감지 — WD 결과 자체가 이미 캐릭터 태그를 분류해 주므로 DB 조회 불필요. WD 출력에 character 카테고리 정보가 없으면(태그 문자열만 있으면) 기존 hf_wd_tagger 응답 구조를 확인해 카테고리 정보를 활용하고, 그것도 불가하면 충돌 감지는 conflicting 후보 저장 없이 생략 (전수 비교로 회귀 금지)

### 2. 판정 원칙 (기존 유지 + 명확화)

- 입력 캐릭터 태그 고신뢰 검출 → pass
- 저신뢰/미검출 → warning (boy 포함)
- 대표 머리색 명확 충돌 → warning (reject 후보로 사유 기록)
- reject는 다른 캐릭터 고신뢰 검출 등 명백한 충돌 근거가 있을 때만
- 검사 대상: 입력 프롬프트의 캐릭터 태그·대표 머리색·포함된 multicolor·(보정으로 추가된) 눈색만. 프롬프트 밖 태그 검사 금지.

### 3. 성능

- 이미지당 DB 조회는 해당 캐릭터 관련 데이터만. 전체 캐릭터 목록 적재 금지.

## 완료 기준

- `cd backend && ../.venv/Scripts/python.exe -m pytest tests/test_identity_checker.py tests/test_character_image_service_v2.py -q` 통과
- `cd backend && ../.venv/Scripts/python.exe -m pytest tests/ -q` 기존 실패 3건 외 통과 (단, test_v2_generation_pipeline.py가 다른 작업자 변경으로 일시 실패하면 그 파일은 무시하고 보고에 명시)
- 커밋 금지, 스코프 밖 파일 수정 금지
