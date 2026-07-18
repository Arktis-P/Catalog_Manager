# 이미지 리뷰 V2 후속 수정 계획

## 1. 문서 목적

이 문서는 `feature/image-review-v2` 브랜치의 1차 구현 검토 결과와 사용자 피드백을 바탕으로, 다음 개발 단계에서 수정해야 할 항목을 정리한다.

기준 문서:

- `docs/PLAN_IMAGE_GENERATION_REVIEW_V2.md`
- `docs/PLAN_V2_EXECUTION.md`

이번 계획은 기존 V2 구현을 폐기하지 않고, 현재 구조를 보완하는 것을 원칙으로 한다.

---

## 2. 우선 수정 범위

### 2.1 자동 품질 검사 구체화

현재 품질 검사는 파일 유효성, 해상도, 빈 이미지, 흐림과 일부 픽셀 기반 얼굴·손 보조 지표를 사용한다. 후속 작업에서는 실제 `bad anatomy`를 걸러낼 수 있도록 검사 단계를 확장한다.

우선 검사 대상:

1. 신체 비율 이상
   - 머리와 몸통 비율이 극단적으로 비정상적임
   - 팔·다리 길이 또는 관절 위치가 명확히 어긋남
   - 목·어깨·허리 연결이 붕괴함
   - 좌우 팔다리의 개수나 위치가 비정상적임
2. 손과 손가락 이상
   - 손가락 개수 이상
   - 손가락 융합
   - 손이 팔이나 물체와 비정상적으로 결합됨
   - 손의 방향과 관절 구조가 명확히 잘못됨
3. 추가 신체 오류
   - 추가 팔·다리
   - 신체 부위 누락
   - 복수 인물의 신체가 융합됨

구현 방향:

- 기존 `quality_checker.py`의 파일·흐림 검사와 보조 지표는 유지한다.
- 고정 영역 픽셀 분석만으로 reject하지 않는다.
- 애니메이션 이미지에 적용 가능한 포즈·손·신체 검출 모델 또는 멀티모달 비전 분석을 추가한다.
- 모델 판정 결과는 구조화된 사유 코드로 저장한다.
- 명확한 신체 오류만 `quality_reject`, 불확실한 경우는 `quality_warning`으로 처리한다.
- 실제 생성 이미지 표본으로 오탐·미탐을 측정하고 임계값을 설정값으로 이동한다.

필수 저장 사유 예시:

- `body_proportion_anomaly`
- `extra_limb`
- `missing_limb`
- `joint_anomaly`
- `hand_anomaly`
- `finger_count_anomaly`
- `body_fusion`

---

### 2.2 Danbooru 활용 범위 수정

Danbooru 위키 본문을 자동 보정의 핵심 데이터로 사용하지 않는다. 캐릭터 외형 태그 수집에서는 Danbooru API 또는 Pybooru의 related tags 기능을 소극적으로 활용한다.

원칙:

- 캐릭터별 관련 태그 후보를 related tags에서 수집한다.
- 수집 대상은 머리색, 머리 모양, multicolor, 눈색, 기타 외형 태그로 제한한다.
- related tags 결과를 그대로 확정하지 않고, 동시 등장 수와 관련도 기준을 적용한다.
- 위키는 사람이 확인할 수 있는 참고 링크로 유지한다.
- 위키 조회 실패가 생성·재생성 파이프라인을 막아서는 안 된다.

수정 대상:

- 관련도 수집기가 related tags API 응답을 우선 후보군으로 사용하도록 변경
- 현재 위키 본문을 조회하고 로그만 남기는 형식적 단계는 제거하거나 사용자 참고용으로 축소
- API 제한, 캐시, 재시도, 부분 실패 처리를 유지

---

### 2.3 V2 이미지 재생성을 V2 파이프라인에 통합

V2 리뷰 화면의 수동 재생성도 일반 V2 생성과 동일한 파이프라인을 사용해야 한다.

통합 플로우:

```text
현재 카드의 기본 프롬프트로 1장 생성
    ↓
auto quality 검사
    ↓
auto identity 검사
    ↓
결과에 따른 자동 재생성·보정
    ↓
최종 결과를 V2 카드에 표시
```

수정 사항:

- 기존 `ReviewRegenerateJobManager`의 V1 global regenerate 호출을 V2 전용 Job 또는 `V2GenerationPipeline` 호출로 교체한다.
- `R` 키와 재생성 버튼은 동일한 V2 API를 호출한다.
- 사용자가 카드에서 편집한 프롬프트를 첫 시도 프롬프트로 사용한다.
- 생성 결과는 `quality_status`, `identity_status`, 사유, 시도 횟수, provisional 상태를 포함해 반환한다.
- 재생성 중에는 카드 잠금과 진행 상태를 기존 UI 방식으로 표시한다.
- 완료 후 V1 응답을 임시 변환하지 않고 V2 응답을 직접 갱신한다.

---

### 2.4 보정 프롬프트의 품질 실패 재시도 통일

초기 프롬프트뿐 아니라 보정 프롬프트도 동일한 품질 재시도 규칙을 적용한다.

각 프롬프트 변형의 처리:

```text
보정 프롬프트 생성
    ↓
이미지 1장 생성
    ↓
quality_reject이면 동일 보정 프롬프트로 재시도
    ↓
최대 횟수 실패 후 다음 보정 단계로 이동
```

원칙:

- Negative 프롬프트는 변경하지 않는다.
- 품질 재시도 최대 횟수는 설정값을 사용한다.
- 품질을 통과한 이미지에 대해서만 identity 검사를 수행한다.
- 처리 시간이 늘어나는 것은 허용한다.
- 전체 시도 횟수와 단계별 시도 횟수를 구분해 기록한다.

권장 기록값:

- `total_generation_attempts`
- `prompt_variant_attempts`
- `prompt_revision_level`
- `last_failure_reason`

---

### 2.5 기타 외형 태그의 자동 추가 중단

기타 외형 태그는 identity 자동 보정 과정에서 추가하지 않는다.

자동 보정 범위:

1. 대표 머리색 변경
2. multicolor 태그 제거 또는 추가
3. 눈색 추가
4. 이후에도 실패하면 `identity_reject` 또는 `generation_failed`

다음 태그는 사람의 V2 리뷰에서만 선택한다.

- scar
- dark skin
- horns
- glasses
- eyepatch
- animal ears
- wings
- tail
- 기타 feature 태그

따라서 `V2GenerationPipeline._revision_variants()`의 feature 일괄 추가 단계는 제거한다. 관련 태그는 V2 카드에 선택 가능한 후보로만 표시한다.

---

### 2.6 캐릭터 재현 검사 플로우 단순화 및 성능 개선

재현 검사는 생성 이미지가 해당 이미지를 만들기 위해 입력된 기본 프롬프트의 캐릭터 정보를 포함하는지만 확인한다.

검사 대상:

- 입력 프롬프트의 캐릭터 태그
- 입력 프롬프트의 대표 머리색
- 입력 프롬프트에 실제 포함된 multicolor 태그
- 보정 단계에서 추가된 눈색

검사하지 않는 대상:

- DB에 존재하는 모든 다른 캐릭터 태그와의 전수 비교
- 프롬프트에 없는 기타 외형 태그
- 전체 캐릭터 목록을 매 이미지마다 메모리에 적재하는 처리

판정 원칙:

- 입력 캐릭터 태그가 높은 신뢰도로 검출되면 `identity_pass`
- 입력 캐릭터 태그가 낮은 신뢰도이거나 미검출이면 `identity_warning`
- 원본 boy 캐릭터의 미검출도 `identity_warning`
- 입력한 대표 머리색과 명확히 충돌하는 경우 warning 또는 reject 후보로 기록
- `identity_reject`는 입력 프롬프트와 생성 결과가 명백히 충돌한다고 판단할 충분한 근거가 있을 때만 사용

성능 개선:

- `known_character_tags` 전체 조회를 제거한다.
- WD 태거의 출력 중 입력 프롬프트 관련 태그만 조회한다.
- 필요하면 WD가 반환한 고신뢰 캐릭터 태그 중 일부만 별도 충돌 정보로 저장하되, 전체 DB 전수 비교는 하지 않는다.

---

### 2.7 V2 병합 상태와 실제 병합 기능 연결

V2 리뷰에서도 기존 카탈로그 리뷰와 동일하게 병합 상태를 확인하고 병합·연결 해제를 수행할 수 있어야 한다.

참조 구현:

- Review → Catalog Review → Characters
- `CharacterLinkModal`
- 기존 parent/child character link API

백엔드 응답 추가:

- `is_alternative`
- `parent_character_id`
- `parent_character_tag`
- `parent_display_name`
- `child_count`

UI 동작:

- 병합된 캐릭터는 `altered` 태그를 표시한다.
- `altered` 태그 클릭 시 상위 캐릭터 정보를 확인할 수 있다.
- 병합 버튼은 기존 `CharacterLinkModal`을 실제 병합 정보와 함께 연다.
- 이미 연결된 캐릭터는 연결 해제를 지원한다.
- 병합 완료 후 현재 카드와 목록을 다시 조회한다.

---

## 3. V2 리뷰 카드 UI 개편

### 3.1 카드 레이아웃

현재 가로형 행 레이아웃을 카탈로그 페이지와 유사한 세로형 카드 그리드로 변경한다.

원칙:

- 카드당 대표 이미지 1장만 표시한다.
- 이미지 전체가 카드 안에서 잘리지 않고 보이도록 `object-fit: contain`을 사용한다.
- 여러 이미지가 존재하는 경우 현재 선택 이미지 1장만 표시하고, 좌우 키 또는 카드 내부 컨트롤로 전환한다.
- 카드 자체를 키보드 포커스 단위로 유지한다.

카드 배치 순서:

1. 이미지
   - 생성 이미지 전체 표시
   - 이미지 하단 오버레이에 `quality`, `identity` 상태 표시
   - pass: 중립 또는 색상 없음
   - warning: 노란색
   - reject: 빨간색
2. 캐릭터 이름 및 병합 상태
   - 표시명은 언더바를 공백으로 변환
   - 오른쪽에 `altered` 태그 표시
   - 태그 클릭 시 상위 캐릭터 확인
3. 시리즈 및 포스트 수
   - 왼쪽: 관련도가 가장 높은 copyright 태그의 표시명
   - 오른쪽: 포스트 개수 숫자만 표시
4. 캐릭터 관련 태그
   - 성별
   - 대표 머리색 및 후보 머리색
   - multicolor
   - 머리 모양
   - 눈색
   - 기타 특징
5. 자주 쓰는 추가 태그
   - multicolored
   - gradient
   - colored inner
   - streaked
6. 기본 프롬프트 입력란
7. 하단 버튼
   - Posts
   - Wiki
   - Merge
   - Regenerate
   - Complete
   - Complete 버튼만 파란색 강조

카드에는 품질·재현의 상세 사유를 툴팁 또는 펼침 영역으로 제공한다.

---

### 3.2 카드 및 이미지 크기 설정

V2 리뷰 카드 크기를 앱 설정에서 조절할 수 있도록 한다.

설정 예시:

- `v2_review_card_width`
- `v2_review_image_height` 또는 `v2_review_image_size`
- 사전 설정: small / medium / large
- 필요하면 사용자 지정 픽셀값

동작:

- 이미지 크기에 맞춰 카드 너비와 내부 레이아웃을 자동 조정한다.
- 화면 너비에 따라 카드 열 수가 자동 변경되는 CSS Grid를 사용한다.
- 설정 변경 시 V2 리뷰 페이지에 즉시 반영한다.
- 카드 이미지만으로 대부분의 리뷰가 가능해야 한다.
- Space 키 원본 이미지 보기는 유지한다.

---

### 3.3 리뷰 탭 기본 페이지 변경

Review 탭에 진입했을 때 V2 리뷰가 기본 페이지가 되도록 변경한다.

동작 원칙:

- `/review` → V2 Review
- 기존 Catalog Review와 Appearance Review는 별도 탭으로 유지
- URL 쿼리 또는 경로로 기존 페이지 직접 접근 가능
- 잘못된 mode 값은 V2로 fallback

---

## 4. 병합 추천 오류 조사 및 수정

### 4.1 확인할 문제

다음과 같이 의상 변형 캐릭터의 상위 후보가 무관한 캐릭터로 추천되는 문제가 있다.

- `murasaki_shion_(1st_costume)` → `gawr_gura` 추천
- `ceres_fauna_(1st_costume)` → `gawr_gura` 추천

기대 결과:

- `murasaki_shion_(1st_costume)` → `murasaki_shion`
- `ceres_fauna_(1st_costume)` → `ceres_fauna`

### 4.2 우선 조사 항목

- 후보 목록이 검색어 없이 첫 페이지 기본 정렬 결과만 보여주는지
- `selectedId`가 새 검색 결과의 첫 항목으로 자동 지정되는 로직이 잘못된 추천처럼 보이는지
- 캐릭터 태그의 괄호 suffix 제거 및 기본 태그 추출이 구현되어 있는지
- 같은 시리즈·copyright 정보가 후보 점수에 반영되는지
- parent 후보 API가 검색 문자열을 제대로 전달하는지
- 이전 카드에서 선택된 후보 상태가 다음 카드에 남는지

### 4.3 수정 방향

병합 후보는 단순 포스트 수 또는 첫 결과 순서가 아니라 이름 유사도와 시리즈 관계를 기준으로 우선 정렬한다.

권장 후보 점수:

1. 변형 suffix 제거 후 기본 태그가 완전히 일치
2. 동일 시리즈에 속함
3. 캐릭터 태그 prefix 또는 핵심 토큰 일치
4. 표시명 유사도
5. 포스트 수

태그 정규화 예시:

```text
murasaki_shion_(1st_costume) → murasaki_shion
ceres_fauna_(1st_costume) → ceres_fauna
```

지원해야 할 일반 suffix 예시:

- costume
- outfit
- alternate costume
- first/second costume
- school uniform
- swimsuit
- alter 및 기타 Danbooru 변형 표기

안전장치:

- 이름 유사도가 매우 낮은 후보를 자동 선택하지 않는다.
- 명확한 후보가 없으면 선택 없이 팝업을 연다.
- 추천 근거를 UI에 표시한다.
- 병합 실행 전 현재 캐릭터와 대상 캐릭터의 이름·시리즈·이미지를 비교 표시한다.

테스트 케이스에 위 두 사례를 반드시 추가한다.

---

## 5. 구현 우선순위

### Phase 1: 파이프라인 정확성

1. V2 수동 재생성을 V2 파이프라인에 연결
2. 보정 프롬프트별 동일 품질 재시도 적용
3. 기타 feature 태그 자동 추가 제거
4. identity 검사 전체 캐릭터 조회 제거 및 입력 프롬프트 중심으로 단순화

### Phase 2: 품질 검사 강화

1. bad anatomy 분석 수단 선정
2. 신체 비율·관절·팔다리 검사
3. 손·손가락 검사
4. 500명 검증 배치로 임계값 튜닝

### Phase 3: V2 리뷰 UI

1. 세로형 카드 그리드
2. 카드 및 이미지 크기 설정
3. 상태 오버레이와 태그 배치
4. V2를 Review 기본 탭으로 변경

### Phase 4: 병합

1. V2 병합 상태 API 확장
2. 기존 병합 팝업과 연결
3. 추천 후보 점수 및 정규화 개선
4. 문제 사례 회귀 테스트

### Phase 5: Danbooru 관련도 수집 정리

1. related tags 기반 후보 수집
2. 관련도 및 동시 등장 수 계산
3. 위키 자동 보정 의존 제거
4. 캐시와 API 제한 검증

---

## 6. 완료 기준

- V2 리뷰에서 `R` 재생성을 실행하면 V2 자동 품질·재현 검사와 재시도 과정이 모두 수행된다.
- 초기·보정 프롬프트 모두 같은 품질 재시도 규칙을 사용한다.
- 기타 feature 태그는 자동 생성 프롬프트에 추가되지 않는다.
- identity 검사에서 전체 캐릭터 목록을 매번 조회하지 않는다.
- bad anatomy 검사에서 신체 비율과 손가락 오류를 최소 우선 항목으로 판정한다.
- V2 카드가 세로형 그리드이며 이미지 전체와 상태 태그를 표시한다.
- 카드 및 이미지 크기를 설정에서 변경할 수 있다.
- Review 탭의 기본 화면이 V2 Review다.
- V2에서 병합 상태 확인, 병합, 연결 해제가 정상 동작한다.
- `murasaki_shion_(1st_costume)`와 `ceres_fauna_(1st_costume)`의 상위 후보가 각각 올바른 기본 캐릭터로 우선 추천된다.
- 관련 단위 테스트, API 테스트, 프론트 타입 체크 및 빌드가 통과한다.
