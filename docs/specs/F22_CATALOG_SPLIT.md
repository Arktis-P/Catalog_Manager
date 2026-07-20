# F22: 카탈로그 탭 분리 — 캐릭터 기반이 기본, 시리즈 기반은 별도 페이지 (담당: sonnet 5, 프론트 전용)

## 배경

`frontend/src/pages/CatalogPage.tsx` 한 페이지에 두 카탈로그가 함께 있음:

1. 상단 "캐릭터 목록 리뷰 결과" 섹션 — `api.listGlobalCatalog` 기반 (**캐릭터 기반, 계속 사용**)
2. 하단 시리즈 기반 카탈로그 — `api.listCatalog` + stats-row + `CatalogRandomPanel` + 필터 toolbar + `CatalogVirtualGrid` + Edit/Change Series 모달 + Export CSV (**사용 안 함, 분리 대상**)

## 목표

- 기본 페이지(`/`, Catalog 탭)는 **캐릭터 기반 카탈로그만** 표시.
- 시리즈 기반 카탈로그는 새 페이지 `frontend/src/pages/SeriesCatalogPage.tsx`로 **통째로 이동**(삭제 아님 — 기능 그대로 유지).

## 구현

1. `SeriesCatalogPage.tsx` 신규: CatalogPage에서 시리즈 기반 부분 전부 이동 — stats-row(`getCatalogStats`), `CatalogRandomPanel`, 필터 toolbar, `CatalogVirtualGrid`, `CatalogEditModal`, Change Series 모달, Export CSV, `handleRegenerate`(series scope), 관련 state/effect. 페이지 제목 예: "Series Catalog (구버전)".
2. `CatalogPage.tsx` 정리: 캐릭터 기반 섹션만 남김 — `listGlobalCatalog` 목록/Load more, Alternative 필터, 레이팅 -1/0 표시 토글, Refresh, `handleRegenerateGlobal`. 시리즈 관련 state/import/effect 제거. `lastCompletedJob` effect는 각 페이지에서 자기 scope만 처리(`scope === "global"`은 CatalogPage, 그 외는 SeriesCatalogPage — 페이지별로 조건 분기해 유지). 제목/설명 문구는 캐릭터 기반에 맞게 다듬기. 검색(search)·gender·rating 필터는 캐릭터 기반 목록이 사용 중이므로 CatalogPage에 유지(현재 `filters.search/gender/rating`을 globalListFilters가 참조 — 필요한 필터 UI가 기존 toolbar에 있었다면 캐릭터 기반용으로 간단한 필드(search/gender/rating)를 CatalogPage에 남길 것).
3. 라우트: `frontend/src/App.tsx`에 `<Route path="series-catalog" element={<SeriesCatalogPage />} />` 추가. index는 그대로 `CatalogPage`.
4. 내비게이션: `frontend/src/components/Layout.tsx`의 `navItems`에서 "Catalog" 다음에 `{ to: "/series-catalog", label: "Series Catalog" }` 추가.

## 범위

- 수정: CatalogPage.tsx, SeriesCatalogPage.tsx(신규), App.tsx, Layout.tsx
- 금지: backend, review 관련 컴포넌트, 그 외 전부

## 완료 기준

- `cd frontend && npx.cmd tsc --noEmit` 통과 시도 (차단 시 보고 명시)
- git commit 금지. 간결한 보고.
