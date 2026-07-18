# F13: V2 리뷰 탭 정리 + 완료 최근순 보기 (담당: gpt-5.5)

## 필독

- `backend/app/routers/review.py`의 `/review/v2/characters` (~166행: review_status 필터 존재, 정렬 없음) 및 V1 `/review/catalog-global`의 `completed_recent` 구현(~489행, `service.list_catalog_reviews_global`)
- `backend/app/services/review_service.py`의 `list_v2_review_characters`, `list_catalog_reviews_global` (completed_recent 정렬 로직 참고)
- `frontend/src/components/review/V2ReviewPanel.tsx` 상단 기능 영역 (필터/통계/페이지네이션)
- `frontend/src/api/client.ts`, `frontend/src/types/index.ts`

## 범위

- 수정: 위 backend 2개 파일 + `backend/tests/`에 테스트, frontend는 review 컴포넌트·client·types만
- **global.css 수정 시 review 관련 구역만** (Characters/taskbar 구역 금지 — 다른 작업자가 동시 수정 중)
- 금지: CharactersPage, GlobalTaskBar, 파이프라인/체커, docs/

## 요구사항

1. **완료 최근순 보기 (backend)**: `/review/v2/characters`의 `review_status` 패턴에 `completed_recent` 추가 — completed만, `GlobalCharacterReview.updated_at desc` 정렬 (V1 convention과 동일). 서비스 레이어에 정렬 분기 + 유닛 테스트 1~2건.
2. **리뷰 탭 상단 간략화 (frontend)**: V2 패널 상단 기능 영역을 정리:
   - 핵심만 항상 노출: 상태 보기 전환(대기 중 / 완료(최근순)), 검색, 페이지 이동, 통계 요약 1줄
   - 나머지 필터(별점/품질/재현/성별/시리즈/multicolor/프롬프트 수정 등 존재 시)는 「상세 필터」 접이식(details/expand)으로 이동
   - 완료(최근순) 보기에서는 카드가 읽기 전용일 필요는 없음 (기존 저장/완료 동작 유지)
3. 기존 쿼리스트링/기본 동작(기본 pending) 유지. V1 리뷰 탭 불변.

## 완료 기준

- `../.venv/Scripts/python.exe -m pytest tests/ -q --basetemp=.pytest_tmp_f13 -p no:cacheprovider` 관련 통과 (기존 실패 3종 제외)
- `cd frontend && npx.cmd tsc --noEmit` 통과
- 실제 DB·output 무변경, git commit 금지, 간결한 보고
