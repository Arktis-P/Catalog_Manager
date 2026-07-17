# 이미지 생성·자동 검사·V2 리뷰 개발 계획

## 1. 문서 목적

이 문서는 Catalogue Manager의 이미지 생성 및 리뷰 플로우를 처음부터 다시 구축하기 위한 개발 계획이다.

기존 캐릭터 목록과 수집된 기본 데이터는 유지하되, 다음 영역은 V2 기준으로 다시 설계한다.

- 캐릭터 외형 태그 재수집
- 캐릭터 기본 프롬프트 생성
- 캐릭터당 이미지 1장 우선 생성
- 자동 품질 검사
- 자동 캐릭터 재현 검사
- 실패 이미지 자동 재생성
- 임시 대표 이미지 등록
- V2 리뷰 페이지
- 1차 레이팅 분류

이번 계획의 범위에는 다음 항목을 포함하지 않는다.

- 레이팅별 랜덤 선택 가중치
- 레이팅 기반 추가 이미지 생성
- 3·4·5성 최종 세분화
- TXT 내보내기 상세 규칙
- 최종 대표 이미지 고도화

---

## 2. 전체 플로우

```text
캐릭터 목록 유지
    ↓
외형 태그와 관련도 재수집
    ↓
캐릭터 기본 프롬프트 생성
    ↓
캐릭터당 이미지 1장 생성
    ↓
자동 품질 검사
    ├─ quality_reject → 동일 프롬프트로 재생성
    └─ quality_warning 이상
            ↓
      자동 캐릭터 재현 검사
        ├─ identity_reject
        │      → 최신 캐릭터 여부 확인
        │      → 프롬프트 보정 후 재생성
        └─ identity_warning 이상
                ↓
          임시 대표 이미지 등록
                ↓
          V2 리뷰
          - 필수 외형 태그 확인 및 추가
          - 성별 수정
          - 이미지 재생성
          - 캐릭터 병합
          - 1차 레이팅 입력
                ↓
          리뷰 완료
```

---

## 3. 캐릭터 외형 태그 재수집

### 3.1 수집 대상

캐릭터별로 다음 외형 태그를 다시 수집한다.

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
  - 기타 캐릭터 식별에 유용한 외형 태그

기타 외형 태그 목록은 코드에 고정하지 않고 확장 가능한 설정 또는 분류 테이블로 관리한다.

### 3.2 관련도 계산

각 태그는 단순 보유 여부가 아니라 캐릭터와의 관련도를 저장한다.

```text
tag_relevance =
캐릭터 태그와 외형 태그가 함께 등장한 포스트 수
÷
해당 캐릭터 태그의 전체 포스트 수
```

저장 항목:

- `character_id`
- `tag`
- `tag_category`
- `cooccurrence_count`
- `character_post_count`
- `relevance_score`
- `is_prompt_candidate`
- `is_confirmed`
- `collected_at`

관련도 인정 기준은 설정값으로 관리한다. 초기 권장값은 다음과 같이 시작하고, 실제 표본을 통해 보정한다.

- 대표 머리색: 관련도 1위 태그
- 머리 모양: 관련도 0.35 이상
- multicolor 관련 태그: 관련도 0.30 이상
- 눈색: 관련도 0.35 이상
- 기타 외형 태그: 관련도 0.20 이상

낮은 포스트 수에서는 관련도 오차가 크므로, 최소 동시 등장 수 조건을 함께 둔다.

초기 권장값:

- 최소 동시 등장 수: 10
- 전체 포스트 수 20 미만: 자동 확정하지 않고 추천 후보로만 저장
- 전체 포스트 수 20~99: 관련도 기준을 0.10 상향
- 전체 포스트 수 100 이상: 기본 기준 사용

### 3.3 대표 머리색

머리색 태그 중 관련도가 가장 높은 하나를 `primary_hair_color`로 지정한다.

대표 머리색이 동률이거나 관련도 차이가 작으면 자동 확정하지 않고 `needs_review` 상태로 둔다.

### 3.4 Multicolor 관련 태그

다음 계열을 별도 그룹으로 관리한다.

- `multicolored_hair`
- `two-tone_hair`
- `gradient_hair`
- `colored_inner_hair`
- `streaked_hair`
- `colored_tips`
- 색상 streak 계열
- 색상 inner hair 계열

관련도 기준을 통과한 태그만 기본 프롬프트 후보로 인정한다.

모든 후보는 V2 리뷰 화면에 표시하되, 자동으로 프롬프트에 추가하지 않은 태그도 사용자가 선택할 수 있어야 한다.

---

## 4. 캐릭터 기본 프롬프트

### 4.1 기본 구성

기본 프롬프트는 다음 항목만 사용한다.

1. 가중치가 적용된 캐릭터 이름
2. 대표 머리색 1개
3. 관련도가 충분히 높은 multicolor 관련 태그

기본 형식:

```text
1.2::{character name}::, {primary hair color}
```

예시:

```text
1.2::hakurei reimu::, brown hair
```

Danbooru 태그의 밑줄은 NAI 프롬프트에서 공백으로 변환한다.

```text
hakurei_reimu → hakurei reimu
brown_hair → brown hair
```

### 4.2 숫자로 끝나는 캐릭터 이름

캐릭터 이름이 숫자로 끝나면 닫는 가중치 구문 앞에 공백을 추가한다.

```text
1.2::android 18 ::, blonde hair
```

이는 NAI 내부 파싱 문제를 우회하기 위한 예외 규칙이다.

구현 시 캐릭터 이름의 마지막 문자가 숫자인지 검사한다.

### 4.3 Multicolor 태그 추가

multicolor 관련 태그가 관련도 기준을 통과한 경우 대표 머리색 뒤에 추가한다.

```text
1.2::character name::, black hair, colored inner hair
```

단, 다음 조건에서는 자동 추가하지 않는다.

- 관련도가 기준 미만
- 동시 등장 포스트 수가 부족함
- 특정 의상 또는 일시적 형태에서만 나타남
- 실제 다색 머리가 아닌데 오탐으로 수집됨
- 대표 머리색과 충돌함

---

## 5. 이미지 생성

이미지 생성 시 선행 프롬프트, 후행 프롬프트, Negative 프롬프트는 앱 설정값을 사용한다.

최종 Positive Prompt 구성:

```text
{prefix_prompt}, {character_base_prompt}, {suffix_prompt}
```

이번 계획에서는 선행·후행·Negative 프롬프트의 구체적인 내용은 정의하지 않는다.

기본 생성 규칙:

- 캐릭터당 최초 1장 생성
- NAIA를 통한 순차 생성
- 생성 결과 저장 후 자동 검사 수행
- 자동 검사 결과가 확정되기 전에는 임시 대표 이미지로 등록하지 않음

---

## 6. 자동 품질 검사

자동 품질 검사는 캐릭터 재현 검사와 분리한다.

목적:

- 캐릭터가 맞는지와 무관하게 이미지 자체가 리뷰에 사용 가능한 품질인지 판정
- bad anatomy, bad hands, 얼굴 붕괴 등 명확한 실패 이미지를 사람 리뷰 전에 제거

품질 검사는 다음 세 단계로 진행한다.

### 6.1 기본 유효성 검사

검사 항목:

- 파일 디코딩 가능 여부
- 해상도 정상 여부
- 완전 검정 또는 완전 흰 이미지
- 지나친 흐림
- 심각한 압축 손상
- 텍스트, 서명, 워터마크
- 인물 미검출
- 복수 인물 검출
- 인물이 지나치게 잘린 구도

구현 후보:

- Pillow 또는 OpenCV
- Laplacian variance 기반 흐림 검사
- 밝기 분포 기반 빈 이미지 검사
- OCR 또는 비전 모델 기반 문자 검출
- 인물 또는 얼굴 검출 모델

저장 예시:

```json
{
  "file_valid": true,
  "resolution_valid": true,
  "blur_score": 0.81,
  "blank_image": false,
  "person_count": 1,
  "text_detected": false,
  "crop_warning": false
}
```

### 6.2 얼굴 검사

검사 항목:

- 얼굴 검출 여부
- 얼굴 개수
- 얼굴이 화면 밖으로 잘렸는지
- 눈 위치가 심하게 비대칭인지
- 눈 또는 입이 붕괴했는지
- 얼굴이 지나치게 흐린지
- 얼굴이 다른 요소와 융합되었는지

일반 사진용 얼굴 검출기는 애니메이션 이미지에서 정확도가 낮을 수 있으므로 다음을 고려한다.

- 애니메이션 얼굴 검출 모델
- 외부 멀티모달 비전 API
- 두 방식의 교차 검사

얼굴 미검출만으로 즉시 reject하지 않는다. 검출 신뢰도가 낮으면 warning으로 처리할 수 있어야 한다.

### 6.3 신체 검사

검사 항목:

- 추가 팔 또는 추가 다리
- 누락된 팔다리
- 몸통과 팔다리 연결 이상
- 비정상적으로 길거나 뒤틀린 팔
- 손과 다른 신체 부위 또는 물체의 융합
- 비정상적인 손가락
- 복수 인물의 신체 융합
- 목, 어깨, 허리의 심각한 왜곡

구현 후보:

- 포즈 또는 신체 부위 검출 모델
- 손 검출 모델
- 외부 멀티모달 비전 모델
- WD 계열 모델의 품질·결함 태그
- 규칙 기반 최종 판정

손이 보이지 않거나 작거나 가려진 경우에는 손 검사 신뢰도를 낮춘다. 손 미검출만으로 reject하지 않는다.

### 6.4 품질 상태

#### `quality_pass`

- 명확한 품질 오류 없음
- 리뷰에 사용 가능
- 기본 유효성 검사 통과

#### `quality_warning`

- 일부 검사 신뢰도가 낮음
- 경미한 이상 가능성이 있음
- 손 또는 얼굴이 작거나 가려짐
- 사람이 리뷰에는 사용할 수 있음

#### `quality_reject`

- 명확한 bad anatomy
- 심각한 손 또는 손가락 붕괴
- 추가 팔다리 또는 신체 융합
- 얼굴 붕괴
- 이미지 손상
- 인물 없음 또는 복수 인물 중심
- 레이팅 판단에 사용할 수 없음

저장 필드:

- `quality_status`
- `quality_score`
- `quality_reasons`
- `quality_checked_at`
- `quality_checker_version`

화면 요구사항:

- 생성 화면에서 표시 및 필터 가능
- V2 리뷰 화면에서 표시 및 필터 가능
- 카탈로그 화면에서 표시 및 필터 가능

---

## 7. 품질 실패 재생성

`quality_reject`인 경우 동일한 프롬프트로 다시 생성한다.

규칙:

- Negative 프롬프트 변경 없음
- 캐릭터 기본 프롬프트 변경 없음
- seed만 달라진 동일 조건 재생성
- 최대 3장까지 시도

```text
1차 생성 → quality_reject
2차 생성 → quality_reject
3차 생성 → quality_reject
```

3장 모두 실패하면:

```text
generation_status = generation_failed
```

`quality_warning`은 자동 재생성하지 않는다.

---

## 8. 자동 캐릭터 재현 검사

품질 검사 결과가 `quality_warning` 이상인 이미지에 대해서만 수행한다.

권장 수단:

- Hugging Face 기반 WD Tagger 등 Danbooru 태그 출력 모델

검사 목적:

- 생성된 이미지가 기대한 캐릭터로 인식되는지 확인
- 기본 프롬프트에 포함된 태그가 이미지에서 검출되는지 확인

### 8.1 검사 대상

기본 프롬프트에 실제로 들어간 태그만 검사한다.

예시:

```text
1.2::hatsune miku::, aqua hair
```

검사 대상:

- `hatsune_miku`
- `aqua_hair`

검사하지 않는 항목:

- 기본 프롬프트에 없는 눈색
- 기본 프롬프트에 없는 머리 모양
- 기타 외형 태그
- 선행·후행 프롬프트의 구도 또는 배경 태그

### 8.2 캐릭터 태그 검사

WD 결과에서 기대 캐릭터 태그의 신뢰도를 확인한다.

주의사항:

- 희귀 캐릭터는 모델 학습 데이터에 없을 수 있음
- 최근 캐릭터는 검출되지 않을 수 있음
- boy 캐릭터는 낮은 신뢰도 또는 미검출 가능성이 있음

boy 캐릭터는 미검출만으로 `identity_reject` 처리하지 않는다.

### 8.3 대표 머리색 검사

기본 프롬프트의 대표 머리색이 검출되는지 별도 점수로 저장한다.

### 8.4 Multicolor 추천

기본 프롬프트에 multicolor 관련 태그가 없지만, 자동 분석에서 높은 신뢰도로 검출되면 추천 태그로 저장한다.

예시:

- `colored_inner_hair`
- `streaked_hair`
- `gradient_hair`

추천 태그는 자동으로 프롬프트에 추가하지 않고 V2 리뷰 화면에서 선택 가능하게 한다.

### 8.5 재현 상태

#### `identity_pass`

- 기대 캐릭터 태그가 높은 신뢰도로 검출됨
- 대표 머리색이 일치함
- 충돌하는 다른 캐릭터 태그가 높게 검출되지 않음

#### `identity_warning`

- 기대 캐릭터 태그 신뢰도가 낮음
- 캐릭터 태그는 미검출이지만 대표 머리색은 일치함
- 원본이 boy라 검출 신뢰도가 낮음
- 자동 모델이 확실한 결론을 내리지 못함

#### `identity_reject`

- 다른 캐릭터 태그가 높은 신뢰도로 검출됨
- 기대 캐릭터 태그는 낮고 충돌 태그는 높음
- 대표 머리색이 명확히 다름
- 생성 결과가 기본 프롬프트와 명백히 충돌함

단순 미검출은 `identity_warning`으로 처리한다.

저장 필드:

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

자동 재생성은 `identity_reject`인 경우에만 수행한다.

### 9.1 최신 캐릭터 제외

먼저 해당 캐릭터의 Danbooru 최초 포스트 업로드 날짜를 확인한다.

조건:

```text
danbooru_first_posted_at >= 2025-05-01
```

해당 조건이면 NAI 모델에 학습되지 않았을 가능성이 높다고 보고 자동 재생성하지 않는다.

상태:

```text
generation_status = likely_untrained
identity_status = identity_reject
```

### 9.2 프롬프트 보정 순서

최신 캐릭터 제외 조건이 아니면 아래 순서대로 보정한다.

1. Danbooru 위키 확인
2. 대표 머리색 재검토 및 변경
3. multicolor 관련 태그 제거 또는 변경
4. 눈색 추가
5. 기타 외형 태그 추가
6. 최종 실패 처리

#### 1단계: Danbooru 위키 확인

확인 항목:

- 공식 외형 설명
- 다른 이름 또는 태그
- 머리색
- 머리 모양
- 눈색
- 뿔, 안대, 피부색, 흉터 등 특징

#### 2단계: 대표 머리색 변경

후보:

- 관련도 2위 머리색
- 위키에서 확인한 머리색
- 생성 이미지에서 반복적으로 검출되는 머리색

#### 3단계: Multicolor 조정

우선순위:

- 잘못 들어간 multicolor 태그 제거
- 관련도가 높은 구체 태그 추가
- 색상 streak 계열 추가
- colored inner hair 등 구체 태그 추가

일반적인 `multicolored_hair`보다 구체적인 태그를 우선한다.

#### 4단계: 눈색 추가

가장 관련도가 높은 눈색 1개를 추가한다.

#### 5단계: 기타 외형 태그 추가

캐릭터 태그 인식을 방해할 가능성이 낮은 태그부터 추가한다.

예시 우선순위:

- dark skin
- scar
- eyepatch
- glasses
- horns
- animal ears
- 기타 명확한 신체 특징

한 번에 너무 많은 태그를 추가하지 않는다.

### 9.3 성공 프롬프트 저장

보정 프롬프트로 생성한 결과가 `identity_warning` 이상이면 해당 프롬프트를 새 기본 프롬프트로 저장한다.

저장 항목:

- `previous_base_prompt`
- `successful_generation_prompt`
- `prompt_revision_reason`
- `prompt_revision_level`
- `prompt_updated_at`

### 9.4 최종 실패

모든 보정 단계를 적용해도 `identity_reject`이면:

```text
generation_status = generation_failed
identity_status = identity_reject
```

---

## 10. 임시 대표 이미지 등록

다음 조건을 모두 만족하면 임시 대표 이미지로 등록한다.

```text
quality_status >= quality_warning
identity_status >= identity_warning
```

허용 조합:

| 품질 | 재현 | 등록 |
|---|---|---|
| pass | pass | 가능 |
| pass | warning | 가능 |
| warning | pass | 가능 |
| warning | warning | 가능 |
| reject | 모든 상태 | 불가 |
| 모든 상태 | reject | 불가 |

warning은 제거하지 않고 각각 별도 표시한다.

- 품질 확인 필요
- 캐릭터 재현 확인 필요

상태 예시:

```text
image_status = provisional
catalog_status = reviewable
```

---

## 11. V2 리뷰 페이지

기존 리뷰 탭 안에 `V2 Review` 페이지를 새로 추가한다.

기존 리뷰 화면의 구현된 기능은 가능한 한 재사용한다.

### 11.1 카드 표시 정보

- 임시 대표 이미지
- 캐릭터 이름
- 시리즈 이름
- 캐릭터 태그
- 기본 프롬프트
- 원래 성별
- 기본 프롬프트에 포함되지 않은 외형 태그
- multicolor 추천 태그
- 자동 품질 검사 결과
- 자동 재현 검사 결과
- warning 또는 reject 사유
- 현재 레이팅
- 생성 시도 횟수
- Danbooru 최초 등록일
- 최신 캐릭터 미학습 가능성

### 11.2 키 바인딩

#### 레이팅

- `-`: -1성
- `0`~`6`: 해당 레이팅 선택

카드에 현재 선택된 레이팅을 표시한다.

#### 성별 변경

- `g`: 성별 변경

지원 값:

- `1girl`
- `1boy`
- `no_humans`
- `unknown`

기존 성별 변경 기능을 재사용한다.

#### Multicolor 태그

- `c`: multicolor 태그 선택 UI 열기

선택 후보:

- multicolored hair
- two-tone hair
- gradient hair
- colored inner hair
- streaked hair
- colored tips
- 수집된 색상 streak 태그
- 자동 분석 추천 태그

복수 선택을 지원한다.

선택한 태그는 대표 머리색 뒤에 추가한다.

#### 재생성

- `r`: 현재 카드의 기본 프롬프트로 재생성

재생성 시:

- 설정의 선행·후행 프롬프트 사용
- 설정의 Negative 프롬프트 사용
- 카드에 저장된 최신 기본 프롬프트 사용
- 자동 품질 검사와 재현 검사 재수행

#### 원본 이미지 보기

- `Space`: 원본 크기로 이미지 보기

기본 썸네일 크기는 설정에서 변경 가능하게 한다.

#### 캐릭터 병합

- `a`: 캐릭터 병합 팝업 열기

기존 병합 기능을 참고하여 다음을 지원한다.

- 대상 캐릭터 검색
- 두 캐릭터 정보 비교
- 대표 캐릭터 선택
- 태그, 시리즈, 이미지, 리뷰 데이터 병합
- 병합 후 리뷰 큐 갱신

### 11.3 마우스 태그 추가

기본 프롬프트에 포함되지 않은 외형 태그를 카드에 표시한다.

사용자가 태그를 클릭하면:

- 선택 상태 표시
- 기본 프롬프트에 추가
- 프롬프트 미리보기 갱신
- 이후 재생성에서 수정 프롬프트 사용

툴팁 표시 항목:

- 관련도
- 동시 등장 수
- 태그 분류
- 추천 이유

### 11.4 필터

#### 리뷰 상태

- 미리뷰
- 리뷰 완료
- 레이팅 미지정
- 재생성 중
- 생성 실패
- 최신 캐릭터 미학습 가능성

#### 품질 상태

- quality_pass
- quality_warning
- quality_reject

#### 재현 상태

- identity_pass
- identity_warning
- identity_reject

#### 기타

- 성별
- 시리즈
- 포스트 수
- multicolor 태그 보유
- multicolor 추천 보유
- 기본 프롬프트 수정됨
- 병합 후보
- 레이팅

---

## 12. 1차 레이팅 플로우

1차 리뷰에서는 3·4·5성을 정밀하게 나누지 않는다.

판정 순서:

### 1. 사람 또는 사람형 캐릭터인가

아니면 `-1`.

포함 사례:

- 인간형이 아닌 캐릭터
- 동물, 기계, 사물 자체
- 고정 외형이 없는 플레이어 대리 캐릭터
- `admiral_(kantai_collection)`
- `sensei_(blue_archive)`

### 2. 이미지 생성에 실패했는가

실패하면 `0`.

포함 사례:

- 최근 캐릭터라 NAI에 학습되지 않은 경우
- 캐릭터 태그가 작동하지 않음
- 외형 태그를 추가해도 재현되지 않음
- 품질 검사에 계속 실패함

### 3. Boy 캐릭터의 특성이 강하게 남아 있는가

강하면 `1`.

판단 기준:

- 남성적인 얼굴 골격
- 남성적인 헤어스타일
- 원본 남성 캐릭터의 인상이 강함

다음은 boy 특성이 약한 것으로 본다.

- 가슴이 강조되지 않아도 얼굴과 헤어스타일이 여성 캐릭터로 자연스러움
- 원본 성별을 모르면 여성 캐릭터로 볼 수 있음

### 4. 완전히 기피할 태그가 있는가

있으면 `2`.

기피 태그 목록은 추후 설정으로 관리할 수 있게 한다.

### 5. 여성 캐릭터인가

위 조건에 해당하지 않으면 우선 `3`.

이 3성은 최종 3성이 아니라 3·4·5성 2차 분류 대기 상태다.

### 6. 확실한 고선호 캐릭터인가

- 최선호 캐릭터: `6`
- 6성까지는 아니지만 정말 좋아함: `5`
- 나머지: `3`

1차 리뷰에서 주로 사용하는 값:

```text
-1 / 0 / 1 / 2 / 3 / 5 / 6
```

4성은 1차 리뷰에서 사용하지 않는다.

---

## 13. 주요 상태값

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

---

## 14. 구현 우선순위

### Phase 1. 데이터 구조 및 태그 재수집

- 외형 태그 관련도 저장 구조 추가
- 대표 머리색 계산
- multicolor 태그 분류
- 기본 프롬프트 생성기 구현
- 숫자로 끝나는 캐릭터 이름 예외 처리

### Phase 2. 이미지 생성 파이프라인 수정

- 캐릭터당 최초 1장 생성
- 생성 시도 횟수 관리
- 품질 검사 후 다음 단계 이동
- 최대 3장 재생성

### Phase 3. 자동 품질 검사

- 기본 유효성 검사
- 얼굴 검사
- 신체 검사
- quality 상태 및 이유 저장
- 필터 API 추가

### Phase 4. 자동 재현 검사

- WD Tagger 연동
- 캐릭터 태그 신뢰도 계산
- 대표 머리색 신뢰도 계산
- boy 캐릭터 예외 처리
- multicolor 추천 생성
- identity 상태 및 이유 저장

### Phase 5. 재현 실패 보정

- Danbooru 최초 등록일 수집
- 2025-05-01 이후 자동 재생성 제외
- 위키 정보 조회
- 머리색, multicolor, 눈색, 기타 태그 순차 보정
- 성공 프롬프트 기본값 반영

### Phase 6. 임시 등록 및 V2 리뷰

- 임시 대표 이미지 등록 조건 구현
- warning 표시
- V2 Review 페이지 추가
- 기존 키 바인딩 재사용
- `c` multicolor 선택 추가
- 원본 이미지 보기
- 태그 클릭 추가
- 병합 팝업 연결

### Phase 7. 1차 레이팅 완료

- 1차 레이팅 규칙 적용
- 4성 미사용 처리
- 3성 refinement pending 저장
- 리뷰 완료 조건 구현

---

## 15. 구현 시 주의사항

- 품질 검사와 캐릭터 재현 검사는 반드시 분리한다.
- `quality_reject`와 `identity_reject`의 재생성 이유를 혼합하지 않는다.
- 캐릭터 태그 미검출만으로 `identity_reject` 처리하지 않는다.
- boy 캐릭터의 미검출은 기본적으로 `identity_warning`이다.
- 자동 검사 결과는 최종 판정이 아니라 리뷰 우선순위 및 자동 재시도 판단용이다.
- 프롬프트 보정 성공 이력은 반드시 저장한다.
- 자동 검사 모델이나 기준이 바뀌면 재검사가 가능하도록 검사 버전을 저장한다.
- V2 Review는 기존 리뷰 기능을 최대한 재사용하되 기존 페이지를 제거하지 않는다.
- 대규모 데이터를 고려하여 목록 API, 필터, 이미지 로딩은 페이지네이션과 지연 로딩을 사용한다.
