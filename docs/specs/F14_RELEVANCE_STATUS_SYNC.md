# F14: V2 관련도 수집 후 상태·표시 컬럼 동기화 (담당: gpt-5.5)

## 버그 (오케스트레이터 진단 완료)

V2 관련도 수집(`TagRelevanceService.collect_for_character`)이 완료돼도 Characters 목록에 여전히 "부분 완료"/"외형 미수집"/외형 컬럼 "-"로 표시된다. 원인:

1. `collect_for_character`가 relevance 행과 `primary_hair_color`만 저장하고 **`appearance_status`·`collect_status`를 갱신하지 않음**
2. 목록 화면이 읽는 레거시 외형 컬럼(`hair_color`/`hair_shape`/`multi_color_hair`/`eye_color`/`feature_tags`)을 채우지 않음 (전면 리셋으로 전부 None인 상태)
3. `base_prompt`도 갱신하지 않아 V2 생성 파이프라인 진입 전 프롬프트가 비어 있음

## 필독

- `backend/app/services/tag_relevance_service.py` (`collect_for_character`, `CollectedRelevance.is_prompt_candidate`/`tag_category`)
- `backend/app/services/prompt_service.py`의 `refresh_global_character_base_prompt` (~140행)
- `backend/scripts/v2_reset_for_recollection.py`의 `_recalculate_collect_status` (collect_status 재계산 규칙)
- `backend/app/models/global_character.py`

## 범위

- 수정: `backend/app/services/tag_relevance_service.py` (+ 필요시 prompt_service import)
- 테스트: `backend/tests/` 관련 파일
- 금지: 그 외 전부. 실제 DB·output 수정 금지.

## 구현

`collect_for_character` 성공 경로 마지막(commit 전)에:

1. **레거시 표시 컬럼 채우기**: is_prompt_candidate=True인 행을 category별로 모아 콤마 문자열로 저장 —
   `hair_color`(primary_hair_color 포함 hair_color 후보), `hair_shape`, `multi_color_hair`(multicolor), `eye_color`, `feature_tags`(feature). 후보가 없는 카테고리는 None.
2. **상태 갱신**: `appearance_status="completed"` 설정 후 reset 스크립트의 `_recalculate_collect_status`와 동일 규칙으로 `collect_status` 재계산 (스크립트 함수를 import하지 말고 서비스에 동일 로직 헬퍼로 구현 — 스크립트가 서비스를 참조하도록 바꾸는 것은 허용).
3. **base_prompt 갱신**: `refresh_global_character_base_prompt` 호출 (기존 사용자 수정 프롬프트 보호 규칙은 해당 함수의 기존 동작을 따름).

## 테스트

- 수집 성공 시: appearance_status="completed", collect_status 재계산, 레거시 컬럼 채워짐, base_prompt 생성됨
- 후보 0개 카테고리는 None 유지

## 완료 기준

- `../.venv/Scripts/python.exe -m pytest tests/ -q --basetemp=.pytest_tmp_f14 -p no:cacheprovider` 관련 통과 (기존 실패 3종 제외)
- git commit 금지, 간결한 보고
