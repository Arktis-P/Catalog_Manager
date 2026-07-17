# 이미지 생성·자동 검사·V2 리뷰 개발 계획

## 1. 목적과 범위

기존 캐릭터 목록과 시리즈 정보는 유지하고, 아래 흐름을 V2 기준으로 다시 구축한다.

```text
외형 태그 관련도 재수집
→ 기본 프롬프트 생성
→ 캐릭터당 이미지 1장 생성
→ 자동 품질 검사
→ 자동 캐릭터 재현 검사
→ 조건부 자동 재생성
→ 임시 대표 이미지 등록
→ V2 리뷰
→ 1차 레이팅 완료
```

이번 범위에서 제외한다.

- 레이팅별 랜덤 선택 가중치
- 레이팅 기반 추가 이미지 생성
- 3·4·5성 최종 세분화
- TXT 내보내기 상세 규칙
- 최종 대표 이미지 고도화

---

## 2. 기존 구현 재사용 원칙

V2는 새 리뷰 시스템을 처음부터 별도로 만들지 않는다. 현재 `Global Catalog Review`를 기반으로 확장하고, 자동 검사 결과 구조만 V2에 맞게 분리한다.

### 2.1 그대로 재사용할 기능

| V2 기능 | 기존 구현 | 적용 방법 |
|---|---|---|
| Review 탭 내부 V2 진입 | `frontend/src/pages/ReviewPage.tsx` | 기존 Catalog/Appearance 탭 구조에 V2 탭 추가 |
| 리뷰 카드 | `frontend/src/components/review/CatalogReviewRow.tsx` | 이미지·캐릭터·시리즈·프롬프트·레이팅 UI 재사용 |
| 캐릭터 중심 리뷰 목록 | `GlobalCatalogReviewPanel.tsx` | V2 패널의 기본 구조로 사용 |
| 레이팅 단축키 | `0~6`, `-` | 기존 키 처리 재사용 |
| 성별 변경 | `g`, `cycleGender()` | 기존 구현 재사용 |
| 이미지 재생성 | `r`, 재생성 Job Context | 현재 카드 프롬프트로 재생성하도록 연결 |
| 이미지 이동 | 좌우 화살표 | 복수 이미지가 존재할 때 재사용 |
| 캐릭터 이동 | 상하 화살표 | 그대로 재사용 |
| 외형 태그 토글 | 태그 chip UI | 기본 프롬프트에 태그 추가·제거 |
| 프롬프트 직접 수정 | 카드 textarea | 그대로 유지 |
| Multicolor 선택 UI | `MULTI_HAIR_OPTIONS` | 기존 옵션·토글 로직 재사용 |
| 캐릭터 병합/연결 | `CharacterLinkModal`, `a` | 그대로 재사용 |
| Danbooru 열기 | `q` Posts, `w` Wiki | 재현 실패 검토에 사용 |
| 리뷰 저장 | 완료 API | 레이팅·성별·프롬프트·선택 태그 저장 기반으로 사용 |
| 재생성 진행 표시 | 카드 잠금·배너·Job 상태 | 자동/수동 재생성에 공통 사용 |
| 썸네일 크기 설정 | `review_thumbnail_size` | V2에도 동일 설정 사용 |
| 이미지 자동 상태 배지 | `auto_status` 표시 | V2에서는 quality/identity 배지로 확장 |

### 2.2 수정해서 재사용할 기능

#### 기본 프롬프트

기존 `frontend/src/utils/reviewPrompt.ts`의 다음 기능을 유지한다.

- Danbooru 태그의 `_`를 공백으로 변환
- `1.2::{character name}::` 가중치 적용
- 첫 번째 머리색을 기본 활성화
- multicolor 태그 선택 및 프롬프트 반영

추가 수정:

- 이름이 숫자로 끝나면 닫는 `::` 앞에 공백 삽입
- 관련도 기준으로 대표 머리색 결정
- 관련도 기준을 통과한 multicolor만 기본 활성화
- 성공한 보정 프롬프트를 캐릭터 기본 프롬프트로 저장

#### 자동 검사

기존 `backend/app/services/image_auto_checker.py`를 폐기하지 않고 V2 검사기의 기반으로 사용한다.

현재 재사용 가능한 항목:

- Pillow 이미지 디코딩
- 전체·눈·손 영역 선명도
- 눈 대칭성
- 눈 로컬 대비
- 손가락 패턴 및 추정 개수
- 손이 보이지 않는 경우 검사 생략
- HF WD 태거 호출
- 캐릭터 태그 신뢰도
- 머리색·눈색·성별 비교

변경 필요:

- 현재 `auto_status` 하나에 품질과 재현 결과가 섞여 있으므로 분리
- 픽셀 기반 손·눈 검사는 보조 지표로만 사용
- 품질과 재현 검사 결과 및 사유를 별도 저장

#### 원본 이미지 보기

현재 Space 미리보기는 600px 썸네일을 사용한다.

V2에서는 기존 미리보기 컴포넌트를 확장해 다음을 지원한다.

- 원본 이미지 URL 사용
- 실제 크기 / 화면 맞춤 전환
- 화면보다 큰 경우 스크롤
- Space로 열기·닫기

#### Multicolor `c` 단축키

기존 multicolor 옵션과 태그 토글 로직은 재사용한다. `c` 키를 누르면 기존 옵션을 선택할 수 있는 팝업 또는 포커스 UI를 추가한다.

---

## 3. 전체 처리 흐름

```text
캐릭터 외형 태그 관련도 재수집
    ↓
기본 프롬프트 생성
    ↓
이미지 1장 생성
    ↓
자동 품질 검사
    ├─ quality_reject → 동일 프롬프트로 재생성
    └─ quality_warning 이상
            ↓
      자동 캐릭터 재현 검사
        ├─ identity_reject
        │   ├─ 최근 캐릭터 → likely_untrained
        │   └─ 기존 캐릭터 → 단계별 프롬프트 보정 후 재생성
        └─ identity_warning 이상
                ↓
          임시 대표 이미지 등록
                ↓
          V2 리뷰
          - 성별 확인
          - 외형 태그 추가·제거
          - multicolor 조정
          - 이미지 재생성
          - 캐릭터 병합
          - 1차 레이팅
                ↓
          리뷰 완료
```

---

## 4. 외형 태그 관련도 재수집

### 4.1 수집 대상

- 머리색
- 머리 모양
- multicolor 관련 태그
- 눈색
- 기타 외형 태그
  - glasses
  - horns
  - eyepatch
  - dark skin
  - scar
  - animal ears
  - halo
  - wings
  - tail
  - 기타 캐릭터 식별에 유용한 태그

기타 외형 태그 목록은 확장 가능한 설정 또는 분류 테이블로 관리한다.

### 4.2 관련도 계산

```text
tag_relevance =
캐릭터 태그와 외형 태그의 동시 등장 포스트 수
÷ 캐릭터 태그 전체 포스트 수
```

저장 필드 권장:

- `character_id`
- `tag`
- `tag_category`
- `cooccurrence_count`
- `character_post_count`
- `relevance_score`
- `is_prompt_candidate`
- `is_confirmed`
- `collected_at`

초기 권장 기준:

- 대표 머리색: 관련도 1위
- 머리 모양: 0.35 이상
- multicolor: 0.30 이상
- 눈색: 0.35 이상
- 기타 외형 태그: 0.20 이상
- 최소 동시 등장 수: 10
- 전체 포스트 20 미만: 자동 확정 금지, 추천만 제공
- 전체 포스트 20~99: 기준 +0.10

기준값은 설정에서 변경 가능해야 한다.

### 4.3 대표 머리색

머리색 중 관련도 1위 하나를 `primary_hair_color`로 지정한다. 동률 또는 근소한 차이는 `needs_review`로 둔다.

### 4.4 Multicolor

별도 그룹으로 관리한다.

- `multicolored_hair`
- `two-tone_hair`
- `gradient_hair`
- `colored_inner_hair`
- `streaked_hair`
- `colored_tips`
- 색상 streak 계열
- 색상 inner hair 계열

관련도 기준을 통과한 태그만 기본 프롬프트 후보로 인정한다. 모든 후보는 V2 리뷰에서 선택 가능해야 한다.

---

## 5. 기본 프롬프트

### 5.1 구성

기본 프롬프트에는 다음만 포함한다.

1. 가중치가 적용된 캐릭터 이름
2. 대표 머리색 1개
3. 관련도가 충분한 multicolor 태그

```text
1.2::{character name}::, {primary hair color}
```

예:

```text
1.2::hakurei reimu::, brown hair
```

Danbooru의 `_`는 공백으로 변환한다.

### 5.2 숫자 끝 이름 예외

캐릭터 이름 마지막 문자가 숫자면 닫는 `::` 앞에 공백을 넣는다.

```text
1.2::android 18 ::, blonde hair
```

### 5.3 이미지 생성 프롬프트

선행·후행·Negative 프롬프트는 앱 설정값을 사용한다.

```text
{prefix_prompt}, {character_base_prompt}, {suffix_prompt}
```

캐릭터당 최초 1장만 생성한다.

---

## 6. 자동 품질 검사

품질 검사는 캐릭터 재현 검사와 분리한다.

### 6.1 기본 유효성 검사

검사 항목:

- 파일 디코딩
- 해상도
- 완전 검정·흰 이미지
- 심각한 흐림
- 압축 손상
- 텍스트·서명·워터마크
- 인물 미검출
- 복수 인물
- 지나친 crop

기존 Pillow 처리와 선명도 계산을 재사용하고, 필요한 경우 OCR·인물 검출을 추가한다.

### 6.2 얼굴 검사

검사 항목:

- 얼굴 검출 여부와 개수
- 얼굴 crop
- 눈 위치 비대칭
- 눈·입 붕괴
- 얼굴 흐림
- 얼굴과 다른 요소의 융합

기존 눈 대칭성·로컬 대비·선명도 계산은 보조 지표로 사용한다. 얼굴 미검출만으로 즉시 reject하지 않는다.

### 6.3 신체 검사

검사 항목:

- 추가·누락 팔다리
- 팔다리 연결 이상
- 손과 다른 요소의 융합
- 비정상 손가락
- 몸통·목·어깨 왜곡
- 복수 인물 신체 융합

기존 손 영역·손가락 추정은 보조 지표로 사용한다. 실제 신체 구조 검사는 별도 모델 또는 외부 비전 검사 추가를 전제로 한다.

### 6.4 상태

- `quality_pass`: 리뷰에 사용 가능
- `quality_warning`: 사람이 확인할 수 있으나 자동 판정 불확실
- `quality_reject`: 리뷰에 사용할 수 없는 명확한 품질 실패

저장 필드 권장:

- `quality_status`
- `quality_score`
- `quality_reasons`
- `quality_checked_at`
- `quality_checker_version`

V2 리뷰와 카탈로그에서 상태 표시 및 필터를 지원한다.

---

## 7. 품질 실패 재생성

- `quality_reject`만 자동 재생성
- 프롬프트와 Negative 프롬프트는 변경하지 않음
- 캐릭터당 최대 3장까지 시도
- 3장 모두 실패하면 `generation_failed`
- `quality_warning`은 자동 재생성하지 않음

기존 재생성 Job Manager와 카드 진행 표시를 재사용한다.

---

## 8. 캐릭터 재현 검사

품질이 `quality_warning` 이상인 이미지에만 수행한다.

### 8.1 검사 대상

기본 프롬프트에 포함된 태그만 검사한다.

예:

```text
1.2::hatsune miku::, aqua hair
```

검사 대상:

- `hatsune_miku`
- `aqua_hair`

기본 프롬프트에 없는 눈색·머리 모양·기타 외형 태그는 자동 재현 판정에 포함하지 않는다.

### 8.2 WD 태거 재사용

기존 HF WD 연동을 그대로 사용한다.

- 캐릭터 태그 신뢰도
- 대표 머리색 신뢰도
- 다른 캐릭터 태그 충돌 여부
- 예상하지 않은 multicolor 태그

추가 요구:

- boy 캐릭터 미검출은 reject가 아니라 warning
- 단순 캐릭터 태그 미검출은 warning
- 다른 캐릭터임이 높은 신뢰도로 확인될 때만 reject
- 예상하지 않은 multicolor 고신뢰 태그는 리뷰 추천으로 저장

### 8.3 상태

- `identity_pass`: 해당 캐릭터임이 높은 신뢰도로 확인
- `identity_warning`: 낮은 신뢰도, 미검출, boy 캐릭터 등 판단 불확실
- `identity_reject`: 다른 캐릭터이거나 기본 프롬프트와 명확히 충돌

저장 필드 권장:

- `identity_status`
- `character_confidence`
- `hair_color_confidence`
- `conflicting_character_tag`
- `conflicting_character_confidence`
- `identity_reasons`
- `suggested_multicolor_tags`
- `identity_checked_at`
- `identity_checker_version`

---

## 9. 재현 실패 재생성

`identity_reject`만 자동 재생성한다.

### 9.1 최근 캐릭터 제외

Danbooru 최초 포스트 날짜가 `2025-05-01` 이후면 자동 재생성하지 않는다.

```text
generation_status = likely_untrained
```

### 9.2 프롬프트 보정 순서

1. Danbooru 위키 확인
2. 대표 머리색 재검토 및 변경
3. 잘못된 multicolor 제거 또는 적절한 multicolor 추가
4. 눈색 추가
5. 캐릭터 태그를 방해하지 않는 기타 외형 태그 추가
   - scar
   - dark skin
   - horns
   - eyepatch
   - glasses
   - animal ears 등
6. 계속 실패하면 `identity_reject` 유지

보정 프롬프트로 `identity_warning` 이상이 되면 해당 프롬프트를 새로운 기본 프롬프트로 저장한다.

저장 권장:

- `previous_base_prompt`
- `successful_generation_prompt`
- `prompt_revision_reason`
- `prompt_revision_level`

---

## 10. 임시 대표 이미지 등록

다음 조건이면 임시 대표 이미지로 등록한다.

```text
quality_status >= quality_warning
identity_status >= identity_warning
```

허용 조합:

- quality pass + identity pass
- quality pass + identity warning
- quality warning + identity pass
- quality warning + identity warning

각 warning은 독립 배지로 표시한다.

- 품질 확인 필요
- 캐릭터 재현 확인 필요

---

## 11. V2 리뷰 페이지

### 11.1 구현 방식

`ReviewPage`에 V2 탭을 추가하고, `GlobalCatalogReviewPanel`과 `CatalogReviewRow`를 기반으로 전용 패널·카드를 만든다.

기존 V1 기능은 유지한다.

### 11.2 카드 표시 정보

- 임시 대표 이미지
- 캐릭터 이름과 태그
- 시리즈
- 기본 프롬프트
- 원래 성별
- 기본 프롬프트에 포함되지 않은 외형 태그
- multicolor 추천 태그
- 자동 품질 검사 결과 및 사유
- 자동 재현 검사 결과 및 사유
- 현재 레이팅
- 생성 시도 횟수
- Danbooru 최초 포스트 날짜
- likely_untrained 표시

### 11.3 단축키와 기능

| 키 | 기능 | 구현 방식 |
|---|---|---|
| `0~6`, `-` | 레이팅 | 기존 구현 재사용 |
| `g` | 성별 변경 | 기존 구현 재사용 |
| `c` | multicolor 선택 | 기존 옵션 UI에 단축키 추가 |
| `r` | 현재 기본 프롬프트로 재생성 | 기존 재생성 Job 재사용 |
| `Space` | 원본 이미지 보기 | 기존 Preview 확장 |
| `a` | 캐릭터 병합/연결 | 기존 `CharacterLinkModal` 재사용 |
| `q` | Danbooru Posts | 기존 구현 재사용 |
| `w` | Danbooru Wiki | 기존 구현 재사용 |
| `Enter` | 리뷰 완료 | 기존 저장 흐름 확장 |
| 방향키 | 이미지/캐릭터 이동 | 기존 구현 재사용 |

마우스로 외형 태그를 선택해 기본 프롬프트에 추가·제거할 수 있어야 한다. 기존 태그 chip과 프롬프트 조합 로직을 사용한다.

### 11.4 필터

- 리뷰 미완료 / 완료
- 레이팅 미지정
- `quality_pass / warning / reject`
- `identity_pass / warning / reject`
- `generation_failed`
- `likely_untrained`
- 성별
- 시리즈
- 레이팅
- multicolor 있음 / 추천 있음
- 기본 프롬프트 수정됨

---

## 12. 1차 레이팅 플로우

1. 사람 또는 고정된 사람형 캐릭터가 아닌가?
   - 예: `-1`
   - 고정 외형이 없는 플레이어 대리 캐릭터도 포함
2. 레이팅 가능한 이미지 생성에 실패했는가?
   - 예: `0`
3. boy 캐릭터의 특성이 여전히 강한가?
   - 예: `1`
4. 완전히 기피하고 싶은 태그가 있는가?
   - 예: `2`
5. 그 외 여성 캐릭터인가?
   - 기본 `3`
6. 확실한 고선호인가?
   - 정말 좋아함: `5`
   - 최선호: `6`

1차 리뷰에서는 `4`를 사용하지 않는 것을 권장한다.

주요 값:

```text
-1 / 0 / 1 / 2 / 3 / 5 / 6
```

3성은 이후 3·4·5성 세분화 대상으로 남긴다.

---

## 13. 데이터·상태 구조

### 생성 상태

- `not_generated`
- `generating`
- `generated`
- `generation_failed`
- `likely_untrained`

### 품질 상태

- `quality_pass`
- `quality_warning`
- `quality_reject`

### 재현 상태

- `identity_pass`
- `identity_warning`
- `identity_reject`

### 이미지 상태

- `not_available`
- `provisional`

### 리뷰 상태

- `pending`
- `in_progress`
- `completed`

### 레이팅 단계

- `primary`
- `refinement_pending`
- `final`

기존 `global_character_images.auto_status`는 마이그레이션 기간 동안 유지할 수 있으나, V2 완료 후에는 quality/identity 상태를 기준으로 사용한다.

---

## 14. 신규 구현 목록

현재 코드에서 새로 개발해야 하는 핵심 기능:

1. 외형 태그 관련도·동시 등장 수 수집 및 저장
2. 관련도 기반 대표 머리색·multicolor 선정
3. 숫자로 끝나는 캐릭터 이름의 NAI 예외 처리
4. `quality_status`와 `identity_status` 분리
5. 기본 유효성 → 얼굴 → 신체의 3단계 품질 검사
6. 품질 reject 시 동일 프롬프트 최대 3회 자동 재생성
7. identity reject 전용 단계별 프롬프트 보정
8. Danbooru 최초 포스트 날짜 조회 및 최신 캐릭터 제외
9. 성공한 보정 프롬프트의 기본 프롬프트 승격
10. 예상하지 않은 multicolor 태그 추천 저장
11. V2 전용 상태 필터
12. V2 리뷰 완료 및 1차 레이팅 단계 관리
13. 원본 이미지 보기
14. `c` multicolor 단축키

---

## 15. 구현 순서

### 1단계: 데이터 및 프롬프트

- 외형 관련도 테이블·필드
- 태그 재수집
- 대표 머리색·multicolor 선정
- 기본 프롬프트 생성 규칙
- 숫자 끝 이름 예외

### 2단계: 검사 결과 분리

- quality/identity 모델·스키마·API
- 기존 `image_auto_checker.py` 분리 리팩터링
- 기존 이미지 저장 과정에 새 검사 연결

### 3단계: 재시도 자동화

- quality reject 최대 3회
- identity reject 단계별 보정
- 최신 캐릭터 제외
- 성공 프롬프트 저장

### 4단계: V2 리뷰

- V2 탭·패널·카드
- 기존 레이팅·성별·재생성·병합·태그 UI 연결
- quality/identity 배지와 필터
- `c` 단축키
- 원본 이미지 보기

### 5단계: 검증

- 500명 테스트 배치
- 품질·재현 오탐/미탐 기록
- 임계값 조정
- 자동 재생성 성공률 확인
- 리뷰 속도 비교

---

## 16. 완료 기준

다음 조건을 만족하면 V2 1차 개발을 완료한 것으로 본다.

- 관련도 기반 기본 프롬프트 생성 가능
- 캐릭터당 1장 생성 후 quality/identity 상태 산출
- quality reject 최대 3회 자동 재생성
- identity reject 단계별 보정 및 최신 캐릭터 제외
- warning 이상 이미지 임시 등록
- V2 리뷰에서 기존 핵심 기능 재사용 가능
- 품질·재현 상태 표시 및 필터 가능
- 1차 레이팅 저장 가능
- 500명 검증 배치 결과를 기준으로 임계값 조정 가능
