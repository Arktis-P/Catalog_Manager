# F8: V2 카드 높이 압축 + 키바인딩 변경 (담당: sonnet 5)

사용자 요구: 카드가 세로로 너무 길다. 아래 4가지로 높이를 줄이고 키보드 조작을 바꾼다.

## 착수 전 필독

- `frontend/src/components/review/V2ReviewRow.tsx` (주 수정 대상)
- `frontend/src/components/review/V2ReviewPanel.tsx` (키 핸들러 ~543행 부근)
- `frontend/src/components/review/ReviewShortcutGuide.tsx`
- `frontend/src/styles/global.css`의 `.v2-review-card*`, `.catalog-review-tags*`, `.v2-review-card-actions`

## 범위

- 수정 허용: 위 4개 파일 + 필요시 `frontend/src/utils/reviewPrompt.ts`(export 추가만)
- 금지: backend 전부, 그 외 frontend 파일, docs/

## 1. "시도 n회" 배지 이동 (V2ReviewRow.tsx 337~342행)

`catalog-review-meta` 행을 통째로 제거하고:
- `시도 {generation_attempts}회` 배지는 **generation_attempts > 0일 때만** 시리즈 행(`v2-review-card-series-row`, 332행)의 posts 배지 옆에 렌더.
- 조건부 배지 3종(genStatusBadge, 프롬프트 보정됨, 대표 머리색 확인 필요)도 시리즈 행으로 이동 (조건 없으면 아무것도 렌더 안 됨 → 평상시 한 줄 절약). 시리즈 행이 넘치면 wrap 허용.

## 2. multicolor 옵션 행 삭제 + 태그 한 덩어리로 (346~412행)

- `catalog-review-tags--multi-options` 행(368~380행, optionalMultiChips) **완전 삭제**. 'c' 키 팝업이 동일 기능 제공하므로 중복. `MULTI_HAIR_OPTIONS` import가 미사용이 되면 제거.
- 성별 chip + hairRowChips + featureRowChips(눈색·특징)를 **하나의 flex-wrap 컨테이너**로 합쳐 그룹 간 강제 줄바꿈 제거 (눈색이 머리모양 뒤에 이어짐). suggested chip(추천 multicolor)은 같은 컨테이너 끝에 기존 `review-tag--suggested` 스타일로 이어 붙임.
- CSS: 기존 `.catalog-review-tags--hair/--features/--suggested` 전용 행 스타일 중 V2 카드에서만 쓰이는 마진 정리 (다른 탭(V1/appearance) 레이아웃은 건드리지 말 것 — 클래스가 공유되면 V2 전용 클래스를 새로 두는 방식으로).

## 3. 버튼 한글화·한 줄 배치 (451~493행)

- Posts 링크 **삭제** (`danbooruPostsUrl` import 미사용 시 제거)
- Wiki → `위키`, Merge → `병합`, Regenerate → `재생성`(진행 중 텍스트 "재생성 중..." 유지), Complete → `완료`
- `.v2-review-card-actions`가 항상 한 줄(flex, nowrap)로 나오게 CSS 조정.

## 4. 방향키·이미지 전환 (V2ReviewPanel.tsx 키 핸들러)

- `ArrowLeft`/`ArrowRight`: 이미지 전환(shiftFocusedImage) → **카드 포커스 ±1 이동**으로 변경 (clamp 0..items.length-1). ArrowUp/Down(±gridCols)은 유지.
- 이미지 전환은 **Ctrl+숫자키(1~9)**: `event.ctrlKey`이고 "1"~"9"면 imageIndex = n-1 (범위 밖이면 무시), preventDefault. Ctrl 없는 숫자 0~6은 기존 별점 유지.
- locked 카드에서 허용 키 목록(575행 부근)에 ArrowLeft/Right 추가 (카드 이동은 잠금과 무관).
- 카드 이미지가 2장 이상이면 이미지 하단에 **번호 chip(1,2,3…)** 표시: 현재 인덱스 강조, 클릭으로도 전환 가능. 기존 ‹ › 오버레이 버튼과 `n/m` 카운터는 번호 chip으로 대체(제거)해도 됨.
- `ReviewShortcutGuide.tsx`의 V2 안내 갱신: ←→↑↓ = 카드 이동, Ctrl+1~9 = 이미지 전환.

## 완료 기준

- `cd frontend && npx.cmd tsc --noEmit` 통과 (명령 실행 권한이 없으면 실행 생략하고 보고에 명시)
- V1 리뷰 탭·Appearance 탭 레이아웃/동작 불변
- git commit 금지, 스코프 밖 파일 수정 금지, 변경 요약 보고
