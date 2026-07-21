# UI/UX 개선 계획

## 현재 문제

- 상단 메뉴가 기능 이름을 같은 위계로 나열해 수집 → 생성 → 리뷰 → 결과 확인 흐름을 한눈에 파악하기 어렵다.
- 전역 작업 패널이 작업이 없을 때도 고정 폭을 차지하고, 접힘 상태와 사용자가 조절한 폭을 기억하지 않는다.
- Review의 `V2`, `Catalog Review`, `Appearance`가 이름만으로는 목적과 사용 순서가 명확하지 않다.
- V2 Review는 단축키를 지원하지만 미저장, 저장 중, 실패 상태가 카드 단위로 명확하지 않고 단건 저장 뒤 다음 카드로 이어지는 흐름이 약하다.
- 전역 포커스 표시와 축소 모션 대응 규칙이 일관되지 않다.

## 목표 사용자 흐름

1. `작업` 그룹에서 데이터를 수집하고 이미지를 생성한다.
2. `리뷰`에서 목적에 맞는 검수 모드를 설명만 보고 선택한다.
3. V2 Review에서 진행률과 적용 필터를 확인하고 키보드로 연속 판정한다.
4. 카드의 미저장·저장 중·실패·재생성 상태를 확인하고 실패 항목을 즉시 다시 처리한다.
5. `결과` 그룹에서 캐릭터 또는 시리즈 카탈로그를 확인한다.
6. 전역 작업 패널은 필요할 때 펼치고, 평소에는 상태 요약만 남겨 작업 영역을 확보한다.

## 우선순위와 단계

- Phase 0: 기존 빌드와 핵심 파일, 열린 PR, 주요 사용자 시나리오 확인
- Phase 1: 내비게이션 그룹화, 한국어 명칭 통일, 작업 패널 접기·폭 저장·상태 요약
- Phase 2: Review 모드 설명, 진행/필터 요약, 카드 저장 상태, 저장 후 다음 카드 포커스, 키보드/ARIA 보강
- Phase 3: spacing/radius/focus 토큰, `focus-visible`, 축소 모션·축소 투명도 대응
- Phase 4: 빌드·테스트와 로컬 화면 검증, 인수인계 문서 동기화

## 변경 컴포넌트

- `frontend/src/components/Layout.tsx`
- `frontend/src/components/GlobalTaskBar.tsx`
- `frontend/src/pages/ReviewPage.tsx`
- `frontend/src/components/review/V2ReviewPanel.tsx`
- `frontend/src/components/review/V2ReviewRow.tsx`
- `frontend/src/components/review/ReviewShortcutGuide.tsx`
- `frontend/src/styles/global.css`

## Apple Design 원칙 적용

| 원칙 | Catalogue Manager 적용 | 결정 |
|---|---|---|
| 즉각적 피드백 | 버튼 누름 상태와 카드 저장 상태를 즉시 표시 | 적용 |
| Agency와 forgiveness | 미저장·실패 상태를 카드에 유지하고 최근 완료 목록에서 재수정 경로 제공 | 적용 |
| Wayfinding | 메뉴를 작업·결과·관리로 그룹화하고 Review 모드 설명 제공 | 적용 |
| Spatial consistency | 작업 패널을 같은 기준점에서 접고 펼침 | 적용 |
| Progressive disclosure | 상세 필터와 레이팅 가이드를 보조 영역에 유지 | 적용 |
| Reduced motion | 큰 이동을 제거하고 축소 모션에서는 변형 효과 비활성화 | 적용 |
| Translucency | 기존 상단 계층 표현만 유지하고 축소 투명도 환경에서는 제거 | 제한 적용 |
| Momentum·spring·bounce | 반복 검수 속도와 상태 인지에 이점이 없어 추가하지 않음 | 제외 |

## 완료 기준

- 기존 URL을 유지하면서 메뉴가 실제 업무 흐름 기준으로 읽힌다.
- 작업 패널이 접히고 마지막 폭·접힘 상태가 안전하게 저장되며, 접힌 상태에도 실행·대기·실패·완료 수가 보인다.
- V2 Review에서 남은 수, 현재 필터, 포커스, 카드 저장 상태를 확인할 수 있다.
- 기존 단축키를 유지하고 키보드 포커스가 보인다.
- 저장 실패가 해당 카드에 남고 저장 성공 뒤 다음 논리적 카드로 흐름이 이어진다.
- `prefers-reduced-motion`을 지원한다.
- 프런트엔드 빌드와 관련 백엔드 테스트가 통과한다.

