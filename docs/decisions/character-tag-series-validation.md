# 캐릭터 태그 시리즈 소속 검증

| 항목 | 내용 |
|------|------|
| 결정일 | 2026-06-15 |
| 상태 | 적용됨 |
| 관련 코드 | `wiki_character_collector.py`, `series_membership.py`, `character_service.py`, `appearance_service.py`, `SeriesCharactersModal.tsx`, `GenerationPage.tsx` |
| 관련 일지 | [docs/2026-06-15.md](../2026-06-15.md) |

---

## 배경

기존 수집 방식은 시리즈 태그가 붙은 post에서 **관련 character tag를 넓게 모으는 것**에 가까웠다. 크로스오버 일러스트(예: `hatsune_miku touhou`) 때문에 **해당 시리즈와 무관한 캐릭터**까지 후보에 들어왔고, Touhou 생성 테스트에서 문제가 확인되었다.

`post_count > 0`이나 `*_(series_tag)` suffix 패턴으로는 해결되지 않았다. 대표 태그(`hakurei_reimu` 등)는 suffix 없이 쓰이는 경우가 많고, 크로스오버 post도 충분히 존재하기 때문이다.

---

## 결정

**캐릭터를 “시리즈 post에 한 번 나왔다”가 아니라 “이 시리즈 소속으로 쓸 만하다”는 기준으로 걸러내는 검증 로직**을 파이프라인 전반에 넣는다.

### 1) 수집 — 위키 우선, 부족할 때만 기존 방식

- **1차**: Danbooru wiki API(`wiki_pages.json`)로 시리즈 위키·`list_of_*_characters` 페이지를 찾고, DText `[[tag]]` 링크 중 character(category=4)만 수집한다. HTML 크롤링은 쓰지 않는다.
- **hub 시리즈**(Touhou 등): 위키에 캐릭터 대신 하위 copyright만 나열된 경우, DB에 이미 있는 하위 `series_tag`를 찾아 각각 위키 수집 후 상위 시리즈로 병합한다.
- **fallback**: 위키·하위 병합 후에도 캐릭터가 0명이면, 그때만 기존 post 스캔 + 패턴 검색으로 수집한다. 위키 경로에서는 post 스캔 보조를 기본 끄고, fallback 시에만 켠다.

→ 위키가 있는 시리즈는 **화이트리스트에 가까운 수집**, 위키가 없는 시리즈는 **예전 방식을 유지**하는 절충이다.

### 2) 수집 이후 — 시스템·사람이 이어서 검수

완전 자동 확정은 하지 않고, 여러 단계에서 한 번씩 걸러낸다.

| 단계 | 역할 |
|------|------|
| Appearance 추출 | related tags의 copyright를 보고, 다른 시리즈가 더 강하게 연관되면 `needs_check` + 사유 저장 |
| Characters 팝업 | `needs_check`만 필터해 수동 확인 |
| Generation | `needs_check` 캐릭터는 기본 생성 대상에서 제외; 검토 전용 목록으로만 표시 |

자동 삭제·자동 시리즈 이동은 하지 않는다. 잘못 걸러진 경우를 사람이 되돌릴 여지를 남긴다.

---

## 기대 효과와 한계

**좋은 점:** 수집·외형 추출·생성 각 단계에서 최소 한 번은 시리즈-캐릭터 조합을 의심하게 만들 수 있다. 위키가 잘 정리된 대형 시리즈에서는 post 스캔만 쓸 때보다 오염이 크게 줄어든다.

**아쉬운 점:** end-to-end 자동화는 아니다. 위키가 없거나 hub 하위 시리즈가 DB에 없으면 fallback·수동 정리에 의존하고, `needs_check`가 많으면 사람 검수 부담이 남는다. suffix·affiliation ratio 같은 추가 자동 규칙, 일괄 삭제/이동 API는 후속 과제로 둔다.

---

## 후속 검토

- character tag alias/deprecated 정규화
- `needs_check` 일괄 삭제·시리즈 이동
- affiliation ratio 등 추가 자동 플래그
- wiki/list 출처만 생성 허용
