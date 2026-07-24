# Catalogue Manager 캐릭터 병합 후보 추천 로직 개선안

## 1. 문서 목적

캐릭터 병합 팝업에서 현재 캐릭터와 실제로 같은 인물인 부모 캐릭터를 우선 추천하도록 후보 탐색 및 정렬 로직을 개선한다.

현재 구현은 이름 토큰 유사도, 동일 시리즈 여부, 포스트 수를 조합하고 있으나, 복수의 괄호가 포함된 Danbooru 캐릭터 태그에서 부모 태그의 구조를 제대로 복원하지 못한다. 또한 동일 시리즈 여부가 지나치게 강한 정렬 기준으로 사용되어, 같은 작품에 속할 뿐인 다른 캐릭터가 상위에 노출될 수 있다.

이 문서는 현재 저장소의 다음 구현을 기준으로 작성한다.

- 백엔드 핵심 로직: `backend/app/services/character_link_service.py`
- 후보 API: `backend/app/routers/character_catalog.py`
- 응답 스키마: `backend/app/schemas/character_catalog.py`
- 병합 팝업: `frontend/src/components/CharacterLinkModal.tsx`
- 프론트 타입: `frontend/src/types.ts`

---

## 2. 현재 구현 요약

현재 추천 과정은 다음과 같다.

1. 전체 캐릭터 중 포스트 수가 높은 후보를 일정 수 조회한다.
2. `_base_tag()`로 괄호 내용을 모두 제거한 기본 태그를 구한다.
3. 기본 태그와 정확히 일치하는 캐릭터 또는 현재 태그를 접두어로 가진 변형 태그를 별도로 후보군에 추가한다.
4. 아래 기준으로 정렬한다.
   - 괄호 제거 기본 태그의 정확 일치
   - 동일 시리즈
   - 태그 토큰 유사도
   - 표시 이름 유사도
   - 포스트 수
5. 유사도 신호가 전혀 없는 후보는 제거한다.

기존 구현은 무관한 인기 캐릭터가 무조건 노출되는 문제를 일부 방지하고 있으나, 복수 괄호 태그의 계층 관계를 표현하기에는 부족하다.

---

## 3. 문제 원인

### 3.1 모든 괄호를 제거해 작품 식별자까지 잃음

현재 `_base_tag()`는 태그 안의 모든 괄호 블록을 제거한다.

예시:

```text
kitasan_black_(glided_shrine_to_glory)_(umamusume)
→ kitasan_black
```

하지만 실제 부모 후보는 다음과 같을 가능성이 높다.

```text
kitasan_black_(umamusume)
```

`_(glided_shrine_to_glory)`는 의상·형태 변형이고 `_(umamusume)`는 동명이인 구분 또는 작품 식별자이므로, 두 괄호를 같은 방식으로 제거해서는 안 된다.

동일한 문제가 다음 태그에서도 발생한다.

```text
kama_(teenager)_(fate)
→ 기대 부모: kama_(fate)

takakura_ken_(transformed)_(dandadan)
→ 기대 부모: takakura_ken_(dandadan)
```

### 3.2 중간 단계 부모 태그를 후보군에 주입하지 못함

현재 별도 후보 탐색은 대체로 다음 두 종류만 다룬다.

- 모든 괄호를 제거한 태그
- 현재 태그 전체를 접두어로 가진 더 긴 변형 태그

따라서 아래처럼 현재 태그에서 일부 괄호만 제거한 중간 단계 태그를 찾지 못한다.

```text
meltryllis_(swimsuit_lancer)_(first_ascension)_(fate)
→ meltryllis_(swimsuit_lancer)_(fate)
→ meltryllis_(fate)
```

### 3.3 동일 시리즈가 이름 유사도보다 먼저 정렬됨

현재 정렬 키에서는 `same_series`가 태그·표시 이름 유사도보다 앞에 있다.

이 구조에서는 다음과 같은 현상이 가능하다.

- `murasaki_shion_(1st_costume)`의 부모를 찾을 때 `murasaki_shion`보다 같은 대형 시리즈에 속한 다른 캐릭터가 상위에 노출됨
- `kitasan_black_(...)_(umamusume)`에 대해 `trainer_(umamusume)` 같은 공통 캐릭터가 추천됨

동일 시리즈는 같은 인물임을 의미하지 않는다. 따라서 독립적인 추천 자격이 아니라, 이름 또는 태그 구조가 이미 유사한 후보 사이에서만 사용하는 보조 점수여야 한다.

### 3.4 시리즈명 토큰이 일반 이름 유사도에 포함됨

현재 `similarity_score()`는 캐릭터 태그와 표시 이름의 모든 토큰을 집합으로 만들어 중복 비율을 계산한다.

예를 들어 서로 다른 캐릭터라도 `fate`, `umamusume` 같은 토큰 하나를 공유하면 유사도 신호가 생길 수 있다. 대형 시리즈에서는 이 신호가 실제 인물 이름보다 과도하게 자주 발생한다.

### 3.5 포스트 수가 낮은 정확한 부모를 놓칠 가능성

기본 후보군은 포스트 수 상위 항목으로 제한된다. 정확한 부모 태그가 존재하더라도 포스트 수가 낮고 현재의 단순 기본 태그 주입 조건에 걸리지 않으면 후보군에 포함되지 않는다.

---

## 4. 목표 동작

### 4.1 핵심 원칙

1. **괄호 앞의 기본 캐릭터명이 같은 후보를 가장 먼저 탐색한다.**
2. **현재 태그의 괄호 그룹 일부를 제거해 만들 수 있는 실제 태그를 최우선 후보로 처리한다.**
3. **현재 태그와 더 많은 괄호 그룹을 공유하는 후보에 더 높은 우선순위를 준다.**
4. **동일 시리즈 여부는 이름·구조 유사성이 확보된 후보의 보조 점수로만 사용한다.**
5. **포스트 수는 최종 동률 해소용으로만 사용한다.**
6. **추천 근거가 없는 다른 인기 캐릭터는 기본 추천 목록에 표시하지 않는다.**

### 4.2 기대 결과

| 현재 캐릭터 태그 | 기대되는 상위 부모 후보 |
|---|---|
| `murasaki_shion_(1st_costume)` | `murasaki_shion` |
| `kitasan_black_(glided_shrine_to_glory)_(umamusume)` | `kitasan_black_(umamusume)` |
| `kama_(teenager)_(fate)` | `kama_(fate)` |
| `meltryllis_(swimsuit_lancer)_(first_ascension)_(fate)` | `meltryllis_(swimsuit_lancer)_(fate)`가 있으면 1순위, 없으면 `meltryllis_(fate)` |
| `takakura_ken_(transformed)_(dandadan)` | `takakura_ken_(dandadan)` |

`gawr_gura`, `trainer_(umamusume)`처럼 같은 시리즈에 속할 뿐 이름 구조가 다른 캐릭터는 기본 추천에서 제외하거나 최하위로 내려야 한다.

---

## 5. 권장 구현 방식

## 5.1 태그를 기본 이름과 괄호 그룹으로 분해

기존 `_base_tag()`만 사용하지 말고, 태그 구조를 보존하는 파서를 추가한다.

```python
@dataclass(frozen=True)
class ParsedCharacterTag:
    base: str
    qualifiers: tuple[str, ...]
```

예시:

```text
kitasan_black_(glided_shrine_to_glory)_(umamusume)
```

파싱 결과:

```python
ParsedCharacterTag(
    base="kitasan_black",
    qualifiers=("glided_shrine_to_glory", "umamusume"),
)
```

권장 함수:

```python
def _parse_character_tag(value: str) -> ParsedCharacterTag:
    ...
```

요구 사항:

- 태그는 현재 DB 저장 규칙에 맞춰 소문자와 밑줄 형식을 유지한다.
- 괄호 그룹의 순서를 보존한다.
- 괄호가 없는 태그도 정상 처리한다.
- 파싱 실패 시 전체 태그를 `base`로 취급해 기존 기능이 중단되지 않게 한다.

---

## 5.2 부모·자식 구조 판정 함수 추가

부모 태그는 현재 태그와 기본 이름이 같고, 부모의 괄호 그룹이 자식 괄호 그룹의 **순서를 유지한 부분집합**이면 구조적으로 연결 가능성이 높다.

예시:

```text
부모: kitasan_black_(umamusume)
자식: kitasan_black_(glided_shrine_to_glory)_(umamusume)
```

부모의 `("umamusume",)`는 자식의 `("glided_shrine_to_glory", "umamusume")`에 순서대로 포함되므로 구조적 부모 관계다.

권장 함수:

```python
def _is_ordered_subsequence(
    smaller: tuple[str, ...],
    larger: tuple[str, ...],
) -> bool:
    ...

def _structural_relation(
    anchor: ParsedCharacterTag,
    candidate: ParsedCharacterTag,
    *,
    role: str,
) -> StructuralRelation | None:
    ...
```

판정 기준:

### 부모 후보 모드

- 기본 이름이 정확히 같아야 한다.
- 후보 괄호 수가 현재 캐릭터보다 적어야 한다.
- 후보 괄호 그룹이 현재 캐릭터 괄호 그룹의 순서 유지 부분집합이어야 한다.

### 자식 후보 모드

- 기본 이름이 정확히 같아야 한다.
- 후보 괄호 수가 현재 캐릭터보다 많아야 한다.
- 현재 캐릭터 괄호 그룹이 후보 괄호 그룹의 순서 유지 부분집합이어야 한다.

이 방식은 부모 추천뿐 아니라 “다른 캐릭터를 이 캐릭터의 하위로 연결” 모드에도 대칭적으로 적용할 수 있다.

---

## 5.3 동일 기본 이름 계열을 별도 후보군으로 조회

현재 `_find_normalized_injection_candidates()`를 확장하거나 교체한다.

현재 캐릭터가 아래와 같다면:

```text
kitasan_black_(glided_shrine_to_glory)_(umamusume)
```

다음 계열을 별도로 조회한다.

```text
kitasan_black
kitasan_black_(...)
```

권장 함수:

```python
def _find_same_base_candidates(
    self,
    anchor: GlobalCharacter,
    *,
    exclude_ids: set[int] | None,
    limit: int = 200,
) -> list[GlobalCharacter]:
    ...
```

쿼리 원칙:

```python
character_tag == base
OR character_tag LIKE 'base\_(%'
```

주의 사항:

- 캐릭터 태그가 이미 소문자로 정규화되어 저장되므로 가능하면 `func.lower()`나 `ilike()`를 피하고, 인덱스를 활용할 수 있는 정확 비교와 prefix `LIKE`를 사용한다.
- 밑줄과 `%`는 `_escape_like()`로 이스케이프한다.
- 동일 기본 이름 후보가 지나치게 많은 경우 상한을 둔다.
- 이 후보군은 포스트 수 상위 기본 후보군과 별도로 조회한 뒤 합친다.

이 변경으로 정확한 부모 태그가 포스트 수 상위 400개 안에 들지 않아도 추천 대상에 포함된다.

---

## 5.4 정렬을 “관계 등급 우선” 방식으로 변경

가중치 합산 하나만 사용하는 것보다, 먼저 관계 등급을 정한 뒤 등급 내부에서 점수를 비교하는 방식이 안전하다.

권장 관계 등급:

| 등급 | 조건 | 예시 |
|---|---|---|
| 0 | 구조적으로 정확한 직계 축약 후보 | `meltryllis_(swimsuit_lancer)_(fate)` |
| 1 | 구조적으로 정확한 더 넓은 축약 후보 | `meltryllis_(fate)` |
| 2 | 기본 이름 정확 일치이나 부모·자식 부분집합 관계가 불명확 | 동일 기본 이름의 다른 변형 |
| 3 | 기본 이름 유사도가 높고 동일 시리즈인 후보 | 철자 차이·별칭 대응 |
| 제외 | 동일 시리즈만 같거나 시리즈 토큰만 공유 | `trainer_(umamusume)` |

권장 정렬 키:

```python
sort_key = (
    relation_tier,
    removed_qualifier_count,
    -shared_qualifier_count,
    -base_name_similarity,
    0 if same_series else 1,
    -min(candidate.post_count, POST_COUNT_TIEBREAK_CAP),
    candidate.character_tag,
)
```

핵심은 다음과 같다.

- 구조 관계가 포스트 수보다 항상 우선한다.
- 부모 후보 중 현재 태그에서 가장 적은 괄호만 제거한 후보가 먼저 나온다.
- 동일 단계라면 더 많은 괄호 그룹을 공유하는 후보를 우선한다.
- 동일 시리즈는 구조·이름 신호가 존재할 때만 보조 정렬에 사용한다.
- 포스트 수는 마지막에만 사용한다.

---

## 5.5 기존 `_score()`의 추천 자격 조건 변경

현재는 `same_series`만으로도 추천 근거가 생성된다. 이를 제거해야 한다.

변경 전 개념:

```python
if base_match:
    reason = "base_tag_match"
elif same_series:
    reason = "same_series"
elif tag_sim > 0 or name_sim >= threshold:
    reason = "name_similarity"
```

변경 후 개념:

```python
if structural_relation:
    reason = "structural_parent" 또는 "structural_child"
elif exact_base_match:
    reason = "same_base"
elif base_name_similarity >= STRONG_NAME_THRESHOLD:
    reason = "name_similarity"
else:
    reason = None
```

`same_series`는 `reason`을 생성하지 않고 점수 보정에만 사용한다.

예시:

```python
if reason is not None and same_series:
    score += SAME_SERIES_BONUS
```

추천 목록에서는 `reason is None`인 후보를 계속 제외한다.

---

## 5.6 유사도 계산에서 기본 이름과 괄호 토큰 분리

기존 `similarity_score()`는 전체 태그 토큰을 한 번에 비교한다. 이를 다음 요소로 분리한다.

```python
@dataclass(frozen=True)
class CandidateScore:
    final_score: float
    base_similarity: float
    shared_qualifier_count: int
    same_series: bool
    relation_tier: int
    match_reason: str | None
```

권장 계산 요소:

1. `base_similarity`
   - 괄호 앞 기본 이름끼리 비교
   - 정확 일치 시 `1.0`
   - 그 외 `SequenceMatcher` 또는 토큰 유사도 사용

2. `qualifier_similarity`
   - 괄호 그룹의 정확 일치 개수 또는 비율
   - 시리즈명 하나만 공유하는 경우 이것만으로 추천 자격을 부여하지 않음

3. `structural_relation`
   - 부모·자식 부분집합 관계라면 가장 큰 가산점

4. `same_series`
   - 강한 이름 신호가 있을 때만 소규모 가산점

5. `post_count`
   - 점수가 같은 후보의 순서만 결정

프론트에 표시하는 `similarity_score`는 최종 정렬 점수를 0~1로 정규화한 값으로 유지하거나, 기존 필드 호환을 위해 기본 이름 유사도를 반환할 수 있다. 다만 사용자에게 보이는 `match 95%`가 실제 정렬 이유와 불일치하지 않도록 최종 점수 또는 구조 점수를 표시하는 편이 좋다.

---

## 5.7 검색 입력이 있을 때도 관련도 우선 정렬

현재 수동 검색 결과는 포스트 수 우선으로 정렬된다. 검색 문자열이 입력된 경우에는 다음 순서를 권장한다.

1. 캐릭터 태그 완전 일치
2. 태그 접두어 일치
3. 표시 이름 완전 일치
4. 태그·표시 이름 부분 일치
5. 구조적 관계
6. 포스트 수

수동 검색은 낮은 추천 점수의 결과도 보여줄 수 있어야 하므로 기본 추천과 달리 완전히 제외하지 않는다. 대신 정확한 검색 결과가 인기 캐릭터보다 먼저 나오도록 해야 한다.

---

## 6. 파일별 수정 범위

## 6.1 `backend/app/services/character_link_service.py`

주요 변경 대상이다.

### 추가 또는 교체할 항목

- `ParsedCharacterTag`
- `StructuralRelation` 또는 동등한 내부 자료형
- `_parse_character_tag()`
- `_is_ordered_subsequence()`
- `_structural_relation()`
- `_find_same_base_candidates()`
- 기본 이름 전용 유사도 함수
- 관계 등급 기반 `_score()`
- 부모·자식 방향을 고려하는 `_rank_recommendations()`

### 제거 또는 축소할 항목

- 모든 괄호를 제거한 결과만 사용하는 `_base_tag()` 중심 판단
- 동일 시리즈만으로 `match_reason`을 생성하는 처리
- 전체 태그 토큰을 동일 가중치로 취급하는 유사도
- 포스트 수 상위 후보군에 과도하게 의존하는 fallback

### 유지할 항목

- `exclude_ids`
- 부모·자식 연결 가능 여부 검증
- 1단계 부모 구조 제한
- 유사도 신호가 전혀 없는 후보를 추천 목록에서 제외하는 안전장치
- DB 조회 후 한 번에 정렬하는 현재 서비스 구조

---

## 6.2 `backend/app/routers/character_catalog.py`

API 경로 자체는 유지할 수 있다.

필요한 변경:

- 새 점수 결과에서 `match_reason`과 `similarity_score`를 응답에 전달
- 선택적으로 아래 디버그 정보를 응답에 추가
  - `base_similarity`
  - `shared_qualifiers`
  - `relation_tier`

디버그 필드는 개발 중에만 사용하고, UI에 필요하지 않으면 최종 스키마에는 포함하지 않아도 된다.

---

## 6.3 `backend/app/schemas/character_catalog.py`

기존 호환을 유지하는 최소 변경안:

```python
class CharacterLinkCandidate(BaseModel):
    ...
    similarity_score: float = 0.0
    match_reason: str | None = None
```

위 필드는 그대로 두고 `match_reason` 값만 확장한다.

권장 값:

- `structural_parent`
- `structural_child`
- `same_base`
- `name_similarity`

`same_series`는 단독 추천 근거로 사용하지 않는다.

---

## 6.4 `frontend/src/components/CharacterLinkModal.tsx`

`MATCH_REASON_LABELS`를 새 기준에 맞게 변경한다.

```typescript
const MATCH_REASON_LABELS: Record<string, string> = {
  structural_parent: "괄호 단계 축약 일치",
  structural_child: "괄호 단계 확장 일치",
  same_base: "기본 캐릭터명 일치",
  name_similarity: "이름 유사",
};
```

추가 권장 사항:

- 첫 번째 후보가 구조적 일치라면 `추천` 배지를 표시한다.
- `동일 시리즈`는 단독 추천 근거로 표시하지 않는다.
- 구조적 후보가 없을 경우 “정확한 부모 후보를 찾지 못했습니다. 직접 검색해 주세요.” 문구를 표시할 수 있다.
- 자동 선택은 현재처럼 첫 번째 후보로 유지하되, `linkable=false` 후보가 첫 번째가 되지 않도록 백엔드에서 연결 가능 후보를 우선한다.

---

## 6.5 `frontend/src/types.ts`

`match_reason` 문자열 타입을 제한하고 있다면 새 값을 반영한다.

```typescript
type CharacterLinkMatchReason =
  | "structural_parent"
  | "structural_child"
  | "same_base"
  | "name_similarity";
```

현재 단순 `string | null`이면 필수 변경은 아니다.

---

## 7. 권장 의사 코드

```python
def _score(
    anchor: GlobalCharacter,
    candidate: GlobalCharacter,
    *,
    role: str,
    anchor_series_ids: set[int],
    series_map: dict[int, set[int]],
) -> tuple[tuple, CandidateScore | None]:
    anchor_parsed = _parse_character_tag(anchor.character_tag)
    candidate_parsed = _parse_character_tag(candidate.character_tag)

    relation = _structural_relation(
        anchor_parsed,
        candidate_parsed,
        role=role,
    )

    same_base = anchor_parsed.base == candidate_parsed.base
    base_similarity = _name_similarity(
        anchor_parsed.base,
        candidate_parsed.base,
    )
    same_series = bool(
        anchor_series_ids & series_map.get(candidate.id, set())
    )

    if relation is not None:
        reason = (
            "structural_parent"
            if role == "parent"
            else "structural_child"
        )
        relation_tier = relation.tier
    elif same_base:
        reason = "same_base"
        relation_tier = 2
    elif base_similarity >= STRONG_NAME_THRESHOLD:
        reason = "name_similarity"
        relation_tier = 3
    else:
        return (), None

    # 동일 시리즈는 이미 이름 또는 구조 신호가 있는 경우에만 보조한다.
    series_rank = 0 if same_series else 1

    sort_key = (
        relation_tier,
        relation.removed_count if relation else 999,
        -(relation.shared_count if relation else 0),
        -base_similarity,
        series_rank,
        -candidate.post_count,
        candidate.character_tag,
    )

    final_score = _normalize_candidate_score(...)
    return sort_key, CandidateScore(
        final_score=final_score,
        base_similarity=base_similarity,
        shared_qualifier_count=relation.shared_count if relation else 0,
        same_series=same_series,
        relation_tier=relation_tier,
        match_reason=reason,
    )
```

---

## 8. 테스트 계획

테스트는 현재 저장소의 백엔드 테스트 디렉터리 규칙에 맞춰 추가한다. 핵심은 서비스 단위 테스트와 후보 API 회귀 테스트다.

## 8.1 태그 파서 테스트

```python
def test_parse_character_tag_without_qualifier():
    ...

def test_parse_character_tag_with_single_qualifier():
    ...

def test_parse_character_tag_with_multiple_qualifiers():
    ...
```

검증 예시:

```text
murasaki_shion_(1st_costume)
→ base=murasaki_shion
→ qualifiers=(1st_costume,)

kitasan_black_(glided_shrine_to_glory)_(umamusume)
→ base=kitasan_black
→ qualifiers=(glided_shrine_to_glory, umamusume)
```

## 8.2 구조 관계 테스트

```python
def test_parent_relation_preserves_series_qualifier():
    ...

def test_parent_relation_accepts_bare_base():
    ...

def test_sibling_variant_is_not_direct_parent():
    ...

def test_child_relation_is_symmetric():
    ...
```

반드시 검증할 내용:

- `kitasan_black_(umamusume)`는 구조적 부모
- `kitasan_black`도 더 넓은 부모 후보
- `kitasan_black_(another_costume)_(umamusume)`는 형제 변형이므로 부모 1순위가 아님
- `trainer_(umamusume)`는 기본 이름이 다르므로 구조적 부모가 아님

## 8.3 추천 순위 회귀 테스트

```python
def test_murasaki_shion_parent_ranked_before_other_hololive_character():
    ...

def test_kitasan_black_parent_ranked_before_trainer():
    ...

def test_kama_parent_preserves_fate_qualifier():
    ...

def test_meltryllis_prefers_nearest_existing_parent():
    ...

def test_takakura_ken_parent_preserves_dandadan_qualifier():
    ...
```

기대 순위:

1. 가장 가까운 구조적 부모
2. 더 넓은 구조적 부모
3. 동일 기본 이름의 기타 후보
4. 강한 이름 유사 후보
5. 무관한 동일 시리즈 후보는 제외

## 8.4 동일 시리즈 회귀 테스트

```python
def test_same_series_alone_does_not_create_recommendation():
    ...
```

- 이름과 태그 구조가 다른 두 캐릭터에 동일 시리즈 링크만 부여한다.
- 기본 추천 결과에 해당 후보가 포함되지 않아야 한다.

## 8.5 포스트 수 회귀 테스트

```python
def test_exact_structural_parent_beats_high_post_count_unrelated_character():
    ...
```

- 정확한 부모의 포스트 수를 낮게 설정한다.
- 무관한 동일 시리즈 캐릭터의 포스트 수를 매우 높게 설정한다.
- 정확한 부모가 항상 앞에 나와야 한다.

## 8.6 검색 결과 테스트

```python
def test_manual_search_prioritizes_exact_tag_over_post_count():
    ...
```

- 검색 문자열과 정확히 일치하는 태그가 포스트 수가 낮더라도 첫 번째여야 한다.
- 수동 검색은 추천 기준 미달 후보도 검색어에 일치하면 표시할 수 있어야 한다.

---

## 9. 성능 고려 사항

전체 캐릭터가 수십만 개이므로 매번 전수 Python 정렬을 하면 안 된다.

권장 조회 구조:

1. 동일 기본 이름 계열 조회
   - 정확 태그 또는 prefix `LIKE`
   - 최대 100~200개

2. 일반 유사도 fallback 후보
   - 기존처럼 포스트 수 상위 후보 일부
   - 최대 400개 내외

3. 두 후보군을 ID 기준으로 합침

4. 시리즈 ID를 한 번의 쿼리로 조회

5. Python에서 구조 파싱 및 정렬

추가 DB 컬럼이나 마이그레이션은 1차 개선에서는 필요하지 않다.

후보 조회가 병목이 되는 경우에만 후속 단계에서 다음 파생 컬럼을 고려한다.

```text
base_character_tag
qualifier_count
```

다만 현재는 `character_tag` prefix 조회와 요청당 수백 건 파싱만으로 충분할 가능성이 높다.

---

## 10. 구현 순서

### 1단계: 파서와 구조 관계 구현

- `_parse_character_tag()`
- `_is_ordered_subsequence()`
- `_structural_relation()`
- 순수 함수 단위 테스트

### 2단계: 후보군 탐색 개선

- `_find_same_base_candidates()`
- 기존 포스트 수 후보군과 병합
- 부모·자식 방향에 맞는 구조 후보 주입

### 3단계: 점수와 정렬 교체

- `same_series` 단독 추천 제거
- 관계 등급 우선 정렬
- 포스트 수를 최종 tie-breaker로 이동

### 4단계: API·UI 추천 근거 갱신

- `match_reason` 새 값 적용
- 병합 팝업 한글 라벨 변경
- 정확한 추천이 없을 때 안내 문구 추가

### 5단계: 예시 태그 회귀 테스트

- 사용자 제시 5개 사례
- 무관한 동일 시리즈 캐릭터
- 낮은 포스트 수의 정확한 부모

---

## 11. 완료 조건

다음 조건을 모두 만족하면 개선 작업을 완료한 것으로 본다.

1. `murasaki_shion_(1st_costume)`에서 `murasaki_shion`이 최상위에 표시된다.
2. `kitasan_black_(glided_shrine_to_glory)_(umamusume)`에서 `kitasan_black_(umamusume)`가 최상위에 표시된다.
3. `kama_(teenager)_(fate)`에서 `kama_(fate)`가 최상위에 표시된다.
4. `takakura_ken_(transformed)_(dandadan)`에서 `takakura_ken_(dandadan)`이 최상위에 표시된다.
5. `meltryllis_(swimsuit_lancer)_(first_ascension)_(fate)`는 존재하는 후보 중 괄호 단계가 가장 가까운 부모가 먼저 나온다.
6. `gawr_gura`, `trainer_(umamusume)`처럼 이름이 다른 동일 시리즈 캐릭터가 단지 포스트 수가 높다는 이유로 기본 추천 상위에 나오지 않는다.
7. 정확한 구조적 부모는 포스트 수가 낮아도 무관한 인기 캐릭터보다 앞선다.
8. 직접 검색 기능은 유지되며 정확 일치 태그가 포스트 수보다 우선한다.
9. 기존 부모 연결·해제 및 1단계 계층 제한이 정상 동작한다.
10. 후보 조회가 전체 캐릭터 전수 스캔으로 변경되지 않는다.

---

## 12. 최종 권장안

사용자가 제안한 “괄호 앞까지의 이름이 같은 결과에 높은 점수를 주고, 이후 괄호 내용까지 일치하면 더 높은 점수를 주는 방식”이 올바른 방향이다.

다만 단순 문자열 포함 점수만 추가하기보다 다음 구조로 구현하는 것이 안전하다.

1. 괄호 앞 기본 이름으로 동일 캐릭터 계열을 찾는다.
2. 괄호 그룹을 순서가 있는 구조로 파싱한다.
3. 일부 괄호를 제거했을 때 실제로 존재하는 태그를 구조적 부모로 판정한다.
4. 더 많은 괄호를 공유하는 가장 가까운 부모를 먼저 정렬한다.
5. 동일 시리즈와 포스트 수는 보조 기준으로만 사용한다.

이 방식은 제시된 사례를 직접 해결하면서, 시리즈 규모가 큰 작품에서 무관한 캐릭터가 추천되는 문제도 함께 차단할 수 있다.
