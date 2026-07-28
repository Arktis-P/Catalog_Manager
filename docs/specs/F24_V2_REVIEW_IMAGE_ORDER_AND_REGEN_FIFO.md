# F24: V2 검수 — 이미지 표시 순서(최신 우선) + 재생성 큐 FIFO

## 목표

1. **이미지 표시 순서**: V2 검수 카드에서 이미지가 여러 장이면 **마지막(=가장 최근에 생성/재생성된) 이미지**가 기본으로 표시된다. 이미지 칩 번호(1,2,3…)도 **생성 순서**를 따른다 (3장이면 (3)번이 최신).
2. **재생성 큐 순서**: 재생성 지시를 여러 번 내리면 **지시한 순서대로(FIFO)** 처리된다. 마지막에 지시한 재생성은 대기 중인 재생성 목록의 **맨 뒤**에 들어간다.
   - 단, 재생성 job이 **대량 V2 생성 job보다 우선**이라는 F17 설계는 **그대로 유지**한다. (`대기 중인 재생성들 뒤 + 대량 생성 job 앞`에 삽입)

## 필독

- `backend/app/routers/review.py` — `_to_v2_review_character` (109~147행): 현재 `visible_images`를 `(not is_cover, -cover_score, id)`로 정렬
- `backend/app/services/review_service.py` — `bulk_complete_v2_review_characters` (691~739행): `cover_image_id`가 없을 때의 폴백 정렬
- `backend/app/services/v2_generation_job_manager.py` — `start_regeneration` (99~131행, 특히 121행 `self._queue.appendleft(...)`), `start`(80~97행), `_dispatch_next`(455~479행)
- `frontend/src/components/review/V2ReviewRow.tsx` — `createV2DraftForItem` (102~124행), 이미지 칩 렌더링 (291~308행)
- `frontend/src/components/review/V2ReviewPanel.tsx` — 벌크 저장 payload 구성 (449~470행), `completeItem` (369~393행), `refreshSingleCharacter` (554~572행)
- `backend/tests/test_f15_pause_and_concurrency.py` (205~215행) — 재생성 우선 삽입 기대값 `FakePipeline.started == [1, 9, 2]`
- `backend/tests/test_bulk_complete_v2_review.py` — cover 폴백이 최고 `cover_score`를 고르는 기대값

## 범위

- 수정: 위 backend 3개 파일 + frontend 2개 파일 + 새/기존 테스트
- 금지: `v2_generation_pipeline.py` 내부 로직, V1(카탈로그/외형) 검수 경로(`CatalogReviewPanel`, `CatalogReviewRow`, `GlobalCatalogReviewPanel`, `to_catalog_item`) 변경, 실제 DB·output 파일 수정, git commit

---

## 구현 1 — 이미지 표시 순서

### 백엔드

1. `backend/app/routers/review.py`의 `_to_v2_review_character`에서 `visible_images` 정렬을 **생성 순서(`image.id` 오름차순)** 로 변경한다.

   ```python
   visible_images = sorted(
       (image for image in character.images if not image.is_rejected),
       key=lambda image: image.id,
   )
   ```

   → 프론트로 내려가는 `images` 배열의 마지막 원소가 항상 "가장 최근에 생성된 이미지"가 된다. 칩 번호도 생성 순서와 일치한다.

2. 같은 함수의 `preview_image`는 더 이상 `visible_images[0]`이 아니다. **커버가 지정돼 있으면 커버, 아니면 마지막(최신) 이미지**로 계산한다.

   ```python
   cover_image_id = review.cover_image_id if review else None
   preview_image = next(
       (image for image in visible_images if image.is_cover or image.id == cover_image_id),
       visible_images[-1] if visible_images else None,
   )
   ```

   (`preview_image`는 현재 프론트에서 실제로 소비하지 않지만 스키마에 존재하므로 의미가 깨지지 않게 유지한다.)

3. `review_service.bulk_complete_v2_review_characters`의 폴백 정렬(716~719행)은 **건드리지 않는다.** 이 폴백은 프론트가 `cover_image_id`를 보내지 않은 경우에만 쓰이고, 아래 프론트 변경으로 V2 패널은 항상 `cover_image_id`를 보내게 된다. `test_bulk_complete_v2_review.py`의 기존 기대값(최고 점수 이미지 선택)을 유지하기 위함.

### 프론트엔드

4. `V2ReviewRow.tsx`의 `createV2DraftForItem`: 기본 `imageIndex`를 **마지막 인덱스**로 바꾼다. 기존 `coverIndex` 우선 로직은 제거한다 (재생성해도 `cover_image_id`가 초기화되지 않기 때문에, 커버 우선을 남기면 재생성 결과가 표시되지 않는다).

   ```typescript
   const lastIndex = character.images.length > 0 ? character.images.length - 1 : 0;
   return { imageIndex: lastIndex, ... };
   ```

   `coverIndex` 계산과 그에 딸린 미사용 변수는 삭제한다.

5. `V2ReviewPanel.tsx`의 벌크 저장 payload(449~470행): `defaultCoverIndex`/`defaultImageIndex` 기반 "바뀐 경우에만 cover_image_id 전송" 로직을 없애고, **항상 현재 표시 중인 이미지의 id를 `cover_image_id`로 전송**한다.

   ```typescript
   const selectedImage = item.images[draft.imageIndex];
   const coverImageId = selectedImage ? selectedImage.id : undefined;
   ```

   → 화면에 보이는 이미지와 저장되는 대표 이미지가 항상 일치한다. (단일 저장 `completeItem`은 이미 `image!.id`를 그대로 보내므로 수정 불필요.)

6. `refreshSingleCharacter`(554~572행)는 이미 재생성 완료 후 `createV2DraftForItem(updated)`로 draft를 다시 만들므로, 4번 변경만으로 **재생성 직후 카드가 새 이미지로 갱신**된다. 추가 수정 없이 동작하는지 확인만 한다.

7. 회귀 확인: `isDraftChanged`(92~102행)는 `createV2DraftForItem`과 같은 기준을 쓰므로 자동으로 맞춰진다. 키보드 이미지 이동(`V2ReviewPanel.tsx` 678행 부근)은 `images.length` 기준이라 그대로 동작해야 한다.

---

## 구현 2 — 재생성 큐 FIFO

`backend/app/services/v2_generation_job_manager.py`의 `start_regeneration`에서 `self._queue.appendleft(job.job_id)`(121행)를 **"대기 중인 재생성 job들 바로 뒤 / 첫 generate job 앞"에 삽입**하도록 바꾼다.

8. `_queue`를 앞에서부터 훑어, `kind == "regenerate"`이고 `status == "queued"`인 job이 연속하는 구간의 끝 위치를 찾아 그 자리에 `insert`한다. 예시:

   ```python
   def _regen_insert_index(self) -> int:
       """대기 중인 재생성 job들 뒤, 첫 generate job 앞의 위치를 돌려준다. (_lock 보유 상태에서 호출)"""
       index = 0
       for job_id in self._queue:
           job = self._jobs.get(job_id)
           if job is not None and job.kind == "regenerate":
               index += 1
               continue
           break
       return index
   ```

   그리고 `self._queue.insert(self._regen_insert_index(), job.job_id)`로 교체한다. (`deque.insert`는 파이썬 3.5+에서 지원)

9. 나머지 동작(중복 `character_id` 차단, 실행 중 generate job auto-pause, 재생성 종료 후 auto-resume)은 **그대로 유지**한다. auto-resume이 "마지막 재생성이 끝난 뒤"에만 일어나는 기존 로직도 유지된다.

10. `_dispatch_next`는 `popleft`이므로 수정 불필요.

---

## 테스트

11. `backend/tests/test_f15_pause_and_concurrency.py`의 기존 재생성 테스트는 **그대로 통과해야 한다** (`FakePipeline.started == [1, 9, 2]`). 통과하지 않으면 8번 구현이 잘못된 것이다.
12. 재생성 FIFO 테스트를 추가한다: 대량 generate job 실행 중에 재생성 A → B → C 순으로 지시했을 때 실행 순서가 `A, B, C`이고, 셋 모두 대기 중이던 generate job보다 먼저 실행되는지 확인. (기존 테스트의 `FakePipeline`/`wait_until` 헬퍼 재사용)
13. 이미지 정렬 테스트를 추가한다 (`test_v2_review_api.py`): `cover_score`가 낮은 이미지를 나중에 넣었을 때 `items[0]["images"]`의 순서가 id 오름차순이고 마지막 원소가 가장 나중에 만든 이미지인지 확인. 커버가 지정된 경우 `preview_image`가 커버인지도 확인.
14. `test_bulk_complete_v2_review.py`는 수정 없이 통과해야 한다.

## 완료 기준

- `cd backend && ../.venv/Scripts/python.exe -m pytest tests/ -q --basetemp=.pytest_tmp_f24 -p no:cacheprovider` — 기존에 이미 실패하던 케이스를 제외하고 통과 (실행 전 기준선을 먼저 측정해서 신규 실패와 구분할 것)
- `cd frontend && npx.cmd tsc --noEmit` 통과
- git commit 금지
- 보고: 변경 파일 목록 + 재생성 큐 삽입 위치 규칙 + 테스트 결과(기준선 대비 신규 실패 유무)를 한국어로 간결하게
