# Characters 탭 (전체 캐릭터 카탈로그)

기존 `Series → Characters` 흐름(시리즈를 먼저 등록하고 그 안에서 캐릭터를 찾는 방식)과 별개로,
Danbooru의 `character` 카테고리 태그 전체를 포스트 수 기준으로 직접 수집하고 관리하는 기능이다.
Series 탭과 관련 데이터/로직은 전혀 변경하지 않았고, 새 테이블과 새 화면으로만 구성했다.

## 무엇을 할 수 있나

- Danbooru character 태그를 포스트 수 내림차순으로 전체 수집 (기본 임계값: 포스트 수 10 이상, UI에서 조정 가능)
- 캐릭터별로 related tags를 **한 번만 조회**해서 외형(머리색/형태/눈색/특징), 성별, 관련 시리즈(copyright tag)를 동시에 분류·저장
- 캐릭터 ↔ 시리즈 다대다 관계 지원 (대표 시리즈 1개 + 관련 시리즈 목록)
- 목록에서 검색(이름/외형), 성별·수집 상태 필터, 정렬, 페이지네이션
- 개별/일괄 선택 후 통합 태그 수집, 실패·부분완료 항목만 재시도
- 목록 수집은 중단 지점(체크포인트)을 저장해 재실행 시 이어서 진행 (중복 생성 없이 upsert)
- 통합 태그 수집 작업은 일시정지/재개/취소 가능, 진행 중 캐릭터명과 성공/부분완료/실패 카운트 표시

## 화면 구성

`Series` 탭 오른쪽에 `Characters` 탭이 추가된다 (`frontend/src/pages/CharactersPage.tsx`).

- 상단 카드: 최소 포스트 수 입력 + "전체 캐릭터 목록 수집" 버튼, "선택 캐릭터 통합 태그 수집" / "실패·부분완료 재시도" 버튼
- **작업 진행 상태는 페이지가 아니라 좌측(사이드바) 통합 작업 내역(`GlobalTaskBar`)에 표시된다.** Series/Generation 작업과
  동일한 위치에 카드로 나타나며, 진행률 바(`current`/`total` 기준 — 예: 일괄 통합 태그 수집을 시작한 개수를 전체로
  둔 진행률)와 일시정지/재개/취소 버튼을 제공한다. 목록 수집처럼 총 개수를 미리 알 수 없는 작업은 진행률 바가
  불확정(indeterminate) 상태로 표시된다.
- 목록 테이블(한 줄에 캐릭터 하나씩, 축소된 글꼴로 더 많은 정보를 표시). 각 컬럼은 겹치지 않도록 고정 폭을
  지정했다 (`characters-table-compact` 관련 CSS):
  - 체크박스, Danbooru 위키 바로가기(`W`) 버튼
  - Character: 표시명+태그를 같은 줄에, 30자(`30ch`) 고정 폭으로 표시 (넘치면 말줄임 + hover 시 전체 텍스트 title)
  - Post count
  - 통합 상태: 전체 상태 배지 + 외형/성별/시리즈 개별 수집 여부 미니 배지 (고정 폭 190px로 대표 시리즈 컬럼과 겹치지 않음)
  - 대표 시리즈
  - 머리색(관련도 상위 2개) · 멀티컬러 · 머리 모양 · 눈색 · 기타 외형(각각 관련도 1위 1개) — 항목별로 별도 컬럼에 표시,
    미수집 항목은 `-`
  - 성별: 1boy는 하늘색, 1girl은 분홍색, 그 외(no_humans/미수집)는 회색 배지
  - 행별 "태그 수집" 버튼: 해당 캐릭터 하나만 즉시 통합 태그 재수집 (일괄 작업과 별개로 큐잉됨)
- 관련 시리즈 "개수"와 "마지막 수집 시각" 컬럼은 표에서 제거했다 (필요 시 상세 모달에서 확인)
- 행 클릭(표시명) 시 상세 모달: 외형/성별/시리즈 각각의 세부 상태와 전체 값, 관련 시리즈 전체 목록, 마지막 수집
  시각, 오류 메시지, 재시도 횟수

## 데이터 모델

기존 `series`, `characters` 테이블은 변경하지 않았다. 새로 추가한 테이블:

- **`global_characters`** (`backend/app/models/global_character.py`)
  독립적인 캐릭터 엔티티. `character_tag`(unique), `post_count`, 통합 상태(`collect_status`)와 세부 상태
  (`appearance_status`, `gender_status`, `series_status`)를 각각 컬럼으로 분리해서, 일부 분류가 실패해도
  성공한 결과는 보존하고 실패한 부분만 별도로 표시/재시도할 수 있게 했다. 외형 태그(hair/eye/feature),
  성별, 오류 메시지, 재시도 횟수, 마지막 수집 시각을 함께 저장한다.

- **`character_series_links`** (`backend/app/models/character_series_link.py`)
  `global_characters` ↔ `series` 다대다 조인 테이블. `copyright_tag`는 항상 원본 태그 문자열을 보관하고,
  `series_id`는 매핑된 Series row(nullable). `relevance_rank`/`is_primary`로 대표 시리즈를 표시하고,
  `is_user_edited`가 true인 링크는 재수집 시 덮어쓰지 않는다.

시리즈 매핑 실패 처리: related tags에서 발견한 copyright tag가 기존 `series` 테이블에 없으면
자동으로 새 Series row를 생성한다 (`status="pending"`, note에 자동 생성 표시). 기존 Series 수집/외형추출
파이프라인에는 영향을 주지 않는다.

## 수집 로직

- **목록 수집** (`backend/app/integrations/danbooru/character_catalog_collector.py`,
  `backend/app/services/character_catalog_service.py::collect_list`)
  `tags.json?search[category]=4&search[order]=count` 를 페이지 단위로 순회하며 포스트 수 임계값 미만이
  나오면 중단(내림차순 정렬이므로 이후 페이지도 전부 미달). 페이지마다 upsert 커밋하고, 마지막 처리 페이지를
  `settings` 테이블에 체크포인트로 저장해 재실행 시 이어서 진행한다.

- **통합 태그 수집** (`character_catalog_service.py::collect_tags_for_character`)
  `related_tag.json?query=<tag>` 를 **category 필터 없이 한 번** 호출하면 응답에 모든 카테고리의
  관련 태그가 섞여 반환된다(태그별 `category` 필드 포함). 여기서:
  - 외형/성별: 기존 `appearance_extractor.py`의 `extract_appearance_tags` 그대로 재사용
  - 시리즈: 새로 추가한 `extract_copyright_tags` (category == 3인 태그만 빈도순 추출)

  세 분류는 각각 독립적으로 try/except 처리되어, 하나가 실패해도 나머지는 저장된다. 전체 상태는
  외형/시리즈 성공 여부로 `completed`/`partial`/`failed`를 판정한다.

## 백엔드 API (`/api/character-catalog/...`)

| Method | Path | 설명 |
|---|---|---|
| GET | `/character-catalog/characters` | 목록 조회 (search, gender, collect_status, series_id, post_count 범위, 정렬, 페이지네이션) |
| GET | `/character-catalog/characters/{id}` | 상세 조회 (관련 시리즈 전체 포함) |
| POST | `/character-catalog/list/start` | 전체 목록 수집 시작 (`min_post_count`, `restart`) |
| POST | `/character-catalog/tags/start` | 선택 캐릭터 통합 태그 수집 시작 (`character_ids`) |
| POST | `/character-catalog/tags/retry-failed` | 실패/부분완료 캐릭터만 재시도 |
| GET/POST | `/character-catalog/jobs...` | 작업 조회/일시정지/재개/취소 (Series 작업 큐와 완전히 분리된 별도 큐) |

작업 관리는 `backend/app/services/character_catalog_job_manager.py`에서 처리하며, 기존
`SeriesJobManager`(`collect_job_manager.py`)와 완전히 독립된 큐/스레드를 사용한다. DB 커밋 직렬화만
기존 `db_write_queue`를 공유한다.

## 프론트엔드 구성

- `frontend/src/context/CharacterCatalogJobContext.tsx` — 기존 `CollectJobContext`와 별도의 폴링
  컨텍스트 (Series 작업 알림/상태에 영향 없음)
- `frontend/src/pages/CharactersPage.tsx` — 메인 화면 (작업 버튼만 있고, 진행 상태 UI는 없음)
- `frontend/src/components/CatalogProgressPanel.tsx` — 좌측 통합 작업 내역에 표시되는 진행 카드
  (진행률 바 포함). `frontend/src/components/GlobalTaskBar.tsx`가 Series/Generation 작업과 함께
  이 컴포넌트를 렌더링한다.
- `frontend/src/utils/characterCatalogStatus.ts` — 상태 배지/라벨 매핑
- 타입: `GlobalCharacter`, `CharacterSeriesLinkInfo`, `CatalogJob` (`frontend/src/types/index.ts`)
- API 클라이언트: `frontend/src/api/client.ts`의 `listGlobalCharacters`, `startCatalogListJob`,
  `startCatalogTagsJob`, `retryFailedCatalogTags`, `listCatalogJobs` 등

## 알려진 제약 / 후속 과제

- Danbooru `tags.json`의 `order=count` 페이지네이션은 매우 깊은 페이지(수십만 건)에서 성능이 떨어질 수
  있다. 대량 수집은 임계값을 단계적으로 낮춰가며(예: 500 → 100 → 10) 실행하는 것을 권장한다.
- 대표 시리즈 수동 지정, 관련도 수동 조정, 시리즈 별칭/병합, 자동 갱신 스케줄, 고급 복합 필터는 1차
  구현 범위에서 제외했다 (요청서 11절 참고).
