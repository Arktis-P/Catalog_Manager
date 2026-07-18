# F7: V2 카드 그리드 겹침 핫픽스 (담당: sonnet 5)

## 버그

V2 리뷰 카드 그리드에서 카드들이 세로로 겹쳐 보인다. 카드 높이는 ~983px인데 그리드 행 트랙이 21.9px로 붕괴되어 다음 행 카드가 38px 아래에서 시작한다.

## 오케스트레이터 진단 (브라우저 라이브 검증 완료)

- `.v2-review-grid` (frontend/src/styles/global.css ~3554행): `height: min(78vh, 1080px)` + `overflow: auto` + 암시적 `grid-auto-rows: auto` 조합에서 행 트랙이 콘텐츠를 반영하지 못하고 21.88px로 계산됨 (Chromium).
- 라이브 실험 결과:
  - `aspect-ratio` 제거 → 효과 없음 (원인 아님)
  - **`grid-auto-rows: max-content` 주입 → 즉시 정상화** (카드 top: 159 → 1065 → 1966, 간격 정상)

## 수정 지시

1. `frontend/src/styles/global.css`의 `.v2-review-grid`에 `grid-auto-rows: max-content;` 추가.
2. 수정 후 관련 레이아웃 회귀 점검 (코드 리뷰 수준):
   - 카드 포커스 스크롤(`scrollIntoView` 류)이 여전히 동작하는 구조인지
   - 카드 크기 설정(small/medium/large/커스텀 px) 변경 시 그리드가 정상 재배치되는지 (CSS 변수 `--v2-card-width` 경로 확인)
   - 겹침을 가정한 임시 방편 스타일(있다면)이 남아 있지 않은지
3. 수정 범위는 `frontend/src/styles/global.css` (필요시 V2ReviewPanel.tsx의 인라인 스타일)만. 다른 파일 수정 금지.

## 완료 기준

- `cd frontend && npx.cmd tsc --noEmit` 통과 (CSS만 수정했어도 형식적으로 실행)
- 변경 diff와 점검 결과 보고. git commit 금지.
