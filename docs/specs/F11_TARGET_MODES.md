# F11: 외형 수집·이미지 생성 대상 모드 확장 (담당: sonnet 5)

목표:
1. **외형 태그 수집**(Characters 탭): 기존 "선택된 캐릭터들" / "미수집 전체"에 더해 **"포스트 수 n개 이상"** 모드 추가 (n은 사용자 입력).
2. **이미지 생성**(V2): 대상 분류를 4가지로 — **선택된 캐릭터들 / 현재 페이지 캐릭터들 / 미생성 전체 / 포스트 수 n개 이상**.

## 착수 전 필독

- `backend/app/routers/character_catalog.py` (`start_relevance_collect` ~56행, `collect_all_uncollected_catalog_tags` ~352행, 목록 API의 `min_post_count` 쿼리 파라미터 ~127행)
- `backend/app/services/relevance_collect_job_manager.py`, 관련 서비스의 `list_uncollected_ids`
- `backend/app/routers/generation.py` (V2 생성 시작 API)
- `backend/app/services/v2_generation_job_manager.py`
- `frontend/src/pages/CharactersPage.tsx` (수집 버튼/모드 UI가 있는 곳 — 실제 파일명은 탐색해서 확인)
- `frontend/src/pages/GenerationPage.tsx` (생성 시작 UI — 실제 파일명 탐색)
- `frontend/src/api/client.ts`, `frontend/src/types/index.ts`

## 범위

- 수정: 위 파일들 (frontend + backend 라우터/서비스/스키마/job manager)
- 금지: docs/, 리뷰 UI(V2ReviewPanel/Row), quality/identity checker, 파이프라인 내부 로직

## 구현

### 백엔드

1. 외형(관련도) 수집 시작 API에 대상 모드 확장: 기존 ids 지정 방식 유지 + `min_post_count` 기반 시작 엔드포인트(또는 기존 시작 API에 `target: "selected"|"uncollected"|"min_posts"` + `min_post_count` 필드). 대상 선정 쿼리: `post_count >= n`이고 관련도 미수집(수집 이력 없음 또는 appearance 미완료 — 기존 미수집 판정 로직 재사용)인 캐릭터, `post_count desc, id asc` 정렬.
2. V2 생성 시작 API에 동일한 target 개념: `selected`(ids), `page`(ids — 프론트가 현재 페이지 id 목록 전달), `not_generated`(전체 미생성), `min_posts`(post_count >= n 이고 미생성). 기존 동작과의 하위호환 유지.
3. 두 경우 모두 대상 0명이면 400/404로 명확한 메시지.

### 프론트엔드

4. Characters 탭 수집 UI: 모드 선택(선택됨/미수집 전체/포스트 n개 이상) + n 숫자 입력(기본값은 설정의 `min_character_post_count`). 시작 전 대상 수를 알 수 있으면 표시(기존 패턴 따름).
5. 생성 UI: 4개 모드 선택 + n 입력. "현재 페이지"는 현재 목록 페이지의 캐릭터 id들을 전달.
6. 기존 버튼/플로우 스타일과 일관되게. 진행/폴링 UI는 기존 job 패턴 재사용.

## 완료 기준

- `cd frontend && npx.cmd tsc --noEmit` 통과 시도 (실행 차단 시 보고에 명시, 코드 수동 검토로 대체)
- backend 테스트: 대상 선정 쿼리에 대한 유닛 테스트 1~2건 추가 (`backend/tests/`)
- git commit 금지, 스코프 밖 수정 금지, 변경 요약·API 형태 결정 근거 보고
