# Pending 자동 검사 — 판정 가시성 + 작은 얼굴 의심 큐 + 2단계 확인

기준 브랜치: `agent/pending-review-auto-inspection`
기준 HEAD: `80554208441ae3d4f16a09fd7b7f2dac5ed592ed` 이상

## 목적

현재 자동 검사는 실제 재생성/재검사/0성/-1성 처리까지 동작하지만, 사용자가 화면만 보고는 다음을 구분하기 어렵다.

- 작은 얼굴/캐릭터 프린트가 있는데 센서가 놓쳐 그냥 통과한 것
- 해당 이상을 잡아 재생성했지만 최종적으로 다시 실패하여 0성이 된 것
- 정상적으로 재생성 후 통과한 것
- 비인물이라 -1 후보가 된 것
- 애매해서 자동 판단을 포기한 것

또한 WD의 약한 gallery/print 신호가 현재 prediction threshold에서 잘려 silent pass가 발생할 수 있다. 이 문제를 threshold를 무작정 낮춰 전부 자동 재생성하는 방식으로 해결하지 않는다.

이번 작업의 목표는:

1. 모든 자동 검사 결과에 **지속되는 provenance(무슨 판단을 왜 했는지)** 를 남긴다.
2. 약한 작은 얼굴/옷 프린트 신호는 **자동 재생성하지 않고 `suspect` 큐**로 보낸다.
3. 로컬 작업자가 suspect/0/-1을 1차 확인할 수 있게 한다.
4. 사용자는 V2 화면에서 작업자 확인 결과와 자동 판정 근거를 보고 최종 확인할 수 있게 한다.
5. 이 기능 전에는 전체 31k production run을 확대하지 않는다.

---

## 0. 현재 0성의 의미를 먼저 고정

현재 코드에서 0성은 `regeneration_limit_exhausted`처럼 **이번 자동 검사에서 실제 repair/re-generation 예산을 소진한 경우**에만 기록되어야 한다.

따라서:

- 작은 얼굴을 WD/semantic이 아예 못 잡음 → **0성이 아님**. pass/warning/3성 prefill/undecided일 수 있다.
- 작은 얼굴을 잡음 → semantic_gallery 재생성 → 반복 실패 → repair 예산 소진 → **0성** 가능.

이 의미가 UI에서 바로 보이도록 한다.

---

## 1. 가장 먼저 확인할 기술적 blind spot

`backend/app/services/identity_checker.py`의 `check_identity()`는 WD prediction을 현재 약 `threshold=0.15`에서 잘라 사용한다.

그런데 semantic checker에는 이미 다음과 같은 약한 compound 기준이 있다.

- `WEAK_CHARACTER_PRINT = 0.10`
- 약한 `print_*`
- 약한 `multiple_views`

prediction 단계에서 0.10~0.15 값이 삭제되면 이 규칙은 일부 실제 이미지에서 절대로 동작할 수 없다.

### 수정 원칙

권장:

- local WD prediction threshold를 **0.08~0.10** 범위로 내려 semantic에 약한 신호가 전달되게 한다.
- identity hair/character/gender 판정 threshold는 기존 값 그대로 유지한다.
- 즉 `더 많은 raw tag를 가져오되`, 자동 reject 기준은 그대로/보수적으로 유지한다.

가능하면 semantic에 필요한 태그 집합만 low-score로 보존하는 구조가 더 좋지만, 구현 복잡도가 커지면 전체 tag threshold 0.08로 낮춰도 된다. 로컬 ONNX는 어차피 전체 logits를 계산하므로 CPU inference 비용 증가는 미미하며, 저장 파일도 추가되지 않는다.

실제 알려진 miss 이미지에서 raw score를 확인하여 `character_print 0.10~0.15` 같은 신호가 다시 들어오는지 검증한다.

---

## 2. semantic 결과를 pass / suspect / reject 3단으로 명시

현재 `SemanticCheckResult.status`의 `warning`을 **사용자/작업자 확인용 suspect**로 적극 활용한다.

### reject — 자동 재생성

기존처럼 두 개 이상의 강한/복합 신호가 있는 경우:

- character_print + print clothing
- multiple_views + multi subject
- poster/card/screen + text/multi
- strong gallery/sheet/collage

→ `reject`, semantic_gallery repair

### suspect — 자동 재생성 금지, 확인 큐

다음처럼 실패 가능성은 있으나 자동 재생성하기에는 부족한 경우:

- `character_print` 약한 단일 신호
- `print_shirt/print_dress/...` 약한 신호 + 약한 text
- `multiple_views` 약한 단일 신호
- card/poster/screen 약한 단일 신호
- 작은 얼굴 관련 compound score가 reject threshold 바로 아래

reason 예:

- `gallery_suspect:character_print:0.12`
- `gallery_suspect:print_shirt:0.24`
- `gallery_suspect:multiple_views:0.27`
- `gallery_suspect:panel_or_goods`

suspect는 `identity_status=warning`에 reason을 합치되 `needs_identity_repair()` 또는 repair stage가 이를 자동 regeneration 대상으로 해석하지 않도록 명시적으로 제외한다.

즉 **suspect는 사용자 부담을 줄이는 필터링 장치이지 자동 reject가 아니다.**

---

## 3. 자동 검사 provenance를 영속 저장

현재 `RepairContext.final_action`과 stage_events는 request summary에만 존재해 페이지를 새로고침하면 사라진다. 이를 보완한다.

대규모 DB migration을 피하기 위해 우선 `GlobalCharacterReview.review_note`의 compact marker를 재사용한다.

검사 종료 시 마지막 결과를 한 줄로 기록:

```text
auto_inspection_result=v1;outcome=regenerated_pass;reason=semantic_gallery;regen=1;image=59890
```

허용 outcome 최소 집합:

- `pass`
- `regenerated_pass`
- `suspect`
- `auto_zero`
- `auto_minus_one`
- `auto_one`
- `prefill_three`
- `undecided`
- `tagger_error`

필드 최소:

- `outcome`
- `reason`
- `regen` 실제 추가 생성 이미지 수
- `image` 최종 latest image id
- `checker` identity/semantic version
- `test=1` (page test면)

기존 marker와 중복되어 무한 증가하지 않도록 **동일 종류의 이전 `auto_inspection_result=` 한 줄은 교체**한다.

### outcome 결정 예

- final_action == 0성 → `auto_zero`, reason=`regeneration_limit_exhausted` 또는 최종 stage
- rating -1 candidate → `auto_minus_one`
- regen > 0 && final_action == pass → `regenerated_pass`
- `gallery_suspect:*` 존재 && regen == 0 → `suspect`
- tagger failure → `tagger_error`
- 그 외 정상 → `pass`/`prefill_three`/`undecided`

---

## 4. V2 API에서 provenance 노출

`V2ReviewCharacterResponse`에 최소 다음 필드를 추가한다.

```python
auto_inspection_outcome: str | None = None
auto_inspection_reason: str | None = None
auto_inspection_regen_count: int = 0
auto_inspection_needs_user_review: bool = False
auto_inspection_local_review: str | None = None
```

`_to_v2_review_character()`에서 review_note의 마지막 `auto_inspection_result=` marker를 parse하여 채운다.

`needs_user_review=True` 기본 조건:

- suspect
- auto_zero
- auto_minus_one
- tagger_error
- undecided

`regenerated_pass`는 기본 false이되 audit에서는 볼 수 있어야 한다.

---

## 5. V2 카드에서 사용자가 바로 판정 이유 확인

현재 quality/identity dot은 hover title에만 reason이 있어 너무 숨겨져 있다.

카드에 compact badge를 추가한다.

예:

- `자동통과`
- `재생성 1 → 통과`
- `확인필요 · 작은 얼굴 의심`
- `0성 · 재생성 소진`
- `-1 · 비인물`
- `판정 보류`
- `태거 오류`

badge title/detail에는 raw reason을 표시한다.

특히 rating 0 카드에는 반드시:

`0성 사유: regeneration_limit_exhausted / identity_hair / semantic_gallery ...`

중 하나가 보이게 한다.

사용자가 "이 작은 얼굴 이미지가 0성이라 남아 있는 건가, 그냥 놓친 건가"를 카드만 보고 바로 구별할 수 있어야 한다.

---

## 6. 상세 필터에 자동검사 필터 추가

`/review/v2/characters`에 optional `inspection_outcome` 필터를 추가한다.

최소 UI 옵션:

- 전체
- `사용자 확인 필요`
- `작은 얼굴/프린트 의심`
- `0성 자동판정`
- `-1 자동판정`
- `재생성 후 통과`
- `자동 통과`
- `미검사/태거오류`

SQL은 review_note marker LIKE 또는 rating/reason 조합으로 구현 가능하다. 14만 건에서 LIKE가 부담되면 초기에는 `사용자 확인 필요`만 별도 endpoint로 만들어도 된다. 새 DB index/migration은 실제 성능 측정 없이 추가하지 않는다.

---

## 7. 로컬 작업자 1차 확인 기능

작업자가 사용자 대신 모든 31k 이미지를 다시 보는 방식이 아니다.

대상은 다음으로 한정한다.

1. `suspect`
2. `auto_zero`
3. `auto_minus_one`
4. tagger_error/undecided
5. random pass audit 일부

### 1차 확인 결과를 저장

새 endpoint 또는 작은 CLI/service를 추가:

```text
inspection_local_review=confirmed
inspection_local_review=false_positive
inspection_local_review=missed_failure
inspection_local_review=needs_user
```

권장 API:

```http
POST /api/review/v2/pending-inspection/local-review
{
  "character_id": 123,
  "status": "confirmed|false_positive|missed_failure|needs_user",
  "note": "optional short reason"
}
```

review_note에 compact marker로 저장해 DB migration을 피한다.

### 로컬 작업자 작업 순서

- suspect/0/-1 목록을 조회
- 이미지 + provenance + raw WD reason 확인
- 확실한 경우 `confirmed`
- 자동 판정이 잘못됐으면 `false_positive`
- 자동 pass인데 실제 작은 얼굴 실패를 확인했으면 `missed_failure`
- 애매하면 `needs_user`

`false_positive`/`missed_failure` 사례만 threshold/rule 수정 후보로 수집한다.

---

## 8. 사용자 최종 확인 큐

UI에 `자동검사 확인 필요` 필터를 추가한다.

기본 표시 우선순위:

1. local_review=`needs_user`
2. local_review=`missed_failure` / `false_positive`
3. local_review 미확인 suspect/auto_zero/auto_minus_one
4. 10% audit sample

사용자는 기존 V2 카드 기능을 그대로 사용한다.

- 이미지가 실제 실패 → 재생성 버튼 또는 0성 확정
- 자동 0이 맞음 → 0성 그대로 저장
- 비인물 맞음 → -1 확정
- 정상인데 suspect → 3/5/6 등 기존 레이팅

별도 새로운 최종 리뷰 UI를 만들지 말고 기존 V2 grid를 필터링해 재사용한다.

---

## 9. known miss 우선 확인

사용자가 현재 보고 있는 "작은 얼굴이 배경/옷에 남아 있는데 재생성되지 않은" 항목 3~10개를 먼저 대상으로 한다.

각 항목에 대해 다음 표를 만든다.

| tag | rating | outcome | latest image | WD weak signals | semantic | 왜 regen 안 됐나 |
|---|---:|---|---:|---|---|---|

반드시 구분:

- `auto_zero`라 이미지가 남은 것인지
- semantic miss로 `pass/prefill_three`가 된 것인지
- `suspect`였지만 아직 사용자 확인 전인지
- 이전 버전 checker 결과라 재검사되지 않은 것인지

이 표를 먼저 보고한 뒤, 필요한 최소 규칙만 수정한다.

---

## 10. 회귀 테스트

필수:

1. raw WD 0.10~0.15 character_print가 semantic까지 전달됨
2. weak single signal → suspect/warning, 자동 regen 0
3. strong compound → reject, 자동 regen
4. suspect가 `needs_identity_repair`로 잘못 들어가지 않음
5. auto_zero provenance reason 저장/parse
6. regenerated_pass provenance 저장
7. V2 response provenance fields
8. inspection_outcome 필터
9. local-review marker 저장/갱신
10. test reset은 `test=1` provenance/local-review marker만 안전하게 제거
11. 사용자 수동 rating은 보존

Frontend:

- provenance badge render
- 0성 사유 표시
- 사용자 확인 필요 filter build/typecheck

---

## 11. 완료 보고 형식

1. known miss 3~10건 표
2. 이 중 실제 auto_zero / semantic miss / suspect 개수
3. low-score WD threshold 변경 결과
4. provenance UI 스크린샷 또는 field 예시
5. local worker 1차 확인 큐 건수
6. 사용자 최종 확인 큐 건수
7. 관련 pytest / frontend build
8. commit SHA

### 중요한 원칙

- 추가로 30/100 랜덤 이미지 수동 테스트를 반복하지 않는다.
- known miss + suspect 큐만 집중 확인한다.
- 약한 단일 신호를 곧바로 자동 reject로 올리지 않는다.
- 사용자가 다시 모든 이미지를 훑게 만들지 않는다.
- 자동화의 목표는 **명백한 실패를 자동 repair하고, 애매한 소수만 사람에게 올리는 것**이다.
