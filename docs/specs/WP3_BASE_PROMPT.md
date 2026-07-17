# WP3: 기본 프롬프트 생성 규칙 (담당: gpt 5.5)

기준: `docs/PLAN_IMAGE_GENERATION_REVIEW_V2.md` §2.2(기본 프롬프트), §5 전체.
선행: WP1 완료 (`global_characters.base_prompt`, `primary_hair_color` 존재). WP2와 병행 가능.

## 착수 전 필독 파일

- `frontend/src/utils/reviewPrompt.ts` (기존 프롬프트 조합 로직 — 유지·확장 대상)
- `backend/app/services/generation_prompt_builder.py`
- `backend/app/services/prompt_service.py`

## 범위

- 수정: `frontend/src/utils/reviewPrompt.ts`
- 수정: `backend/app/services/generation_prompt_builder.py` (필요시 `prompt_service.py`)
- 신규: `backend/tests/test_v2_base_prompt.py`
- 프론트 테스트: 기존 프론트 테스트 러너가 없으면 순수 함수로 분리만 해두고 백엔드 테스트로 규칙 검증
- 스코프 밖: UI 컴포넌트, 검사기, Job

## 기능 요구

### 1. V2 기본 프롬프트 조합 (백엔드가 기준 구현, 프론트는 동일 규칙 미러)

```
1.2::{character name}::, {primary hair color}[, {multicolor tags...}]
```

- Danbooru `_` → 공백 변환 (기존 로직 재사용)
- 캐릭터 이름 마지막 문자가 숫자(0-9)면 닫는 `::` 앞에 공백 1개: `1.2::android 18 ::`
- 대표 머리색: `global_characters.primary_hair_color` 1개만
- multicolor: `character_appearance_tag_relevance`에서 `tag_category='multicolor' AND is_prompt_candidate=1`인 태그만 기본 포함
- 조합 결과를 `global_characters.base_prompt`에 저장하는 서비스 함수 제공 (WP2 수집 완료 후 일괄 생성 + 단건 재생성 모두 지원)
- `base_prompt`가 이미 수동 수정된 경우(리뷰에서 저장된 값) 덮어쓰기 여부 플래그 인자로 제어

### 2. 이미지 생성용 최종 프롬프트

```
{prefix_prompt}, {character_base_prompt}, {suffix_prompt}
```

- prefix/suffix/negative는 기존 앱 설정값 사용 (기존 generation_prompt_builder 패턴 유지)
- V1 경로는 깨뜨리지 말 것 — V2 전용 빌더 함수를 추가하는 방식 권장

### 3. 프론트 미러 (`reviewPrompt.ts`)

- 기존 기능 유지: `_`→공백, `1.2::name::` 가중치, 첫 머리색 기본 활성화, multicolor 토글
- 추가: 숫자 끝 이름 공백 규칙, 관련도 기반 기본 활성화(서버가 내려주는 candidate 목록 사용을 전제로 순수 함수 시그니처만 확장 — API 연동은 WP6)

## 테스트 (백엔드)

케이스: 일반 이름 / 숫자 끝 이름(`android_18`) / multicolor 0·1·N개 / primary_hair_color 없음(이름만) / `_` 다수 포함 이름 / 덮어쓰기 플래그 on·off

## 완료 기준

- `cd backend && python -m pytest tests/ -x` 통과
- `cd frontend && npx tsc --noEmit` 통과
- 커밋 금지, 스코프 밖 파일 수정 금지
