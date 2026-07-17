# WP6: V2 리뷰 UI (담당: sonnet 5)

기준: `docs/PLAN_IMAGE_GENERATION_REVIEW_V2.md` §2.1(재사용 표), §2.2(원본 보기·c 단축키), §10, §11, §12.
선행: WP4(quality/identity 응답 필드), WP7(V2 리뷰 API).

## 착수 전 필독 파일

- `frontend/src/pages/ReviewPage.tsx` (탭 구조)
- `frontend/src/components/review/GlobalCatalogReviewPanel.tsx`, `CatalogReviewRow.tsx` (기반 컴포넌트)
- `frontend/src/components/review/ReviewImagePreview.tsx` (Space 미리보기 — 확장 대상)
- `frontend/src/utils/reviewPrompt.ts` (V2 프롬프트 함수 — WP3 산출)
- `frontend/src/api/client.ts`, `frontend/src/types/index.ts`
- `backend/app/routers/review.py`의 V2 엔드포인트 (WP7 산출 — 응답 구조 확인)
- `frontend/src/components/CharacterLinkModal.tsx`, `ReviewRatingStars.tsx`, `ReviewShortcutGuide.tsx`

## 범위

- 수정: `frontend/src/pages/ReviewPage.tsx` (V2 탭 추가 — 기존 탭 불변)
- 신규: `frontend/src/components/review/V2ReviewPanel.tsx`, `V2ReviewRow.tsx` (기존 패널·Row를 기반으로 작성하되 별도 파일 — V1 파일 대규모 수정 금지, 공용 추출이 꼭 필요하면 최소한으로)
- 수정: `frontend/src/components/review/ReviewImagePreview.tsx` (원본 보기 확장)
- 수정: `frontend/src/api/client.ts`, `frontend/src/types/index.ts` (V2 API 연동 타입)
- 수정 허용: `frontend/src/components/review/ReviewShortcutGuide.tsx` (V2 키 안내)
- 스코프 밖: backend 전체, V1 리뷰 동작 변경

## 1. V2 탭·패널

- ReviewPage에 "V2" 탭 추가, `GET /api/review/v2/characters` 목록 사용
- 캐릭터 중심 목록, 페이지네이션·가상화는 기존 패널 방식 재사용
- 필터 바: §11.4 전체 (리뷰 상태, 레이팅 미지정/값, quality/identity 상태, generation_failed, likely_untrained, 성별, 시리즈, 레이팅, multicolor 있음/추천 있음, 프롬프트 수정됨)
- 상단에 진행 통계(있으면 `GET /api/review/v2/stats`)

## 2. V2 카드 (V2ReviewRow)

표시 (§11.2): 임시 대표 이미지(is_provisional), 이름·태그, 시리즈, base_prompt(수정 가능 textarea), 원래 성별, 프롬프트 미포함 외형 태그 chip(클릭으로 추가·제거), multicolor 추천 태그(suggested_multicolor_tags), quality/identity 배지+사유 툴팁, 현재 레이팅, 생성 시도 횟수, first_post_at, likely_untrained 뱃지.

배지: quality_warning "품질 확인 필요", identity_warning "캐릭터 재현 확인 필요" — 독립 표시 (§10).

## 3. 단축키 (§11.3) — 기존 핸들러 재사용

`0~6`/`-` 레이팅, `g` 성별, `r` 재생성(현재 base_prompt로, 기존 재생성 Job Context), `Space` 원본 보기, `a` 병합(CharacterLinkModal), `q`/`w` Danbooru, `Enter` 리뷰 완료(POST complete), 방향키 이동, **신규 `c`**: multicolor 옵션 팝업(기존 MULTI_HAIR_OPTIONS UI를 포커스 가능한 팝업으로, 방향키+Enter 선택, Esc 닫기).

## 4. 원본 이미지 보기 (§2.2)

ReviewImagePreview 확장: 원본 URL 사용(기존 media 라우트의 원본 경로), 실제 크기/화면 맞춤 토글 버튼(또는 키), 화면보다 크면 스크롤, Space 열기/닫기 유지. V1 사용처 동작 불변.

## 5. 레이팅 가이드

1차 레이팅 플로우(§12)를 V2 패널 내 가이드로 표시 (기존 ReviewRatingGuide 참고, V2 전용 문구): -1/0/1/2/3/5/6 권장, 4 비권장 안내.

## 완료 기준

- `cd frontend && npx.cmd tsc --noEmit` 통과
- `cd frontend && npx.cmd vite build` (또는 npm run build) 통과
- V1 리뷰 탭 동작 불변 (V1 파일 diff 최소)
- 커밋 금지, 스코프 밖 파일 수정 금지
