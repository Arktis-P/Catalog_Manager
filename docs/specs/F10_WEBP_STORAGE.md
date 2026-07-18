# F10: 생성 이미지 WebP 저장 전환 (담당: gpt-5.5)

목표: 생성 이미지를 PNG 대신 WebP로 저장해 용량을 크게 줄이되, **원본 해상도 유지 + 시각적 품질 거의 무손실**. 저장·선택(catalog_selected 이동)·썸네일·표시(미디어 서빙) 전 플로우가 WebP를 다뤄야 한다. 기존 PNG 파일과의 공존은 고려하지 않아도 된다(전면 리셋 후 재생성 예정)— 단, 코드가 확장자를 하드코딩으로 가정해 깨지는 곳은 모두 정리할 것.

## 착수 전 필독

- `backend/app/services/generation_service.py` (이미지 바이트 저장 지점 — pending_review 저장)
- `backend/app/services/v2_generation_pipeline.py` (V2 파이프라인의 저장 호출 경로)
- `backend/app/services/character_image_service.py` (catalog_selected 이동 — 확장자 유지 여부 확인)
- `backend/app/routers/media.py` (파일 서빙 + 썸네일 생성 — PNG 가정 여부 확인)
- `backend/app/services/quality_checker.py`, `identity_checker.py` (PIL open — WebP도 동작하는지만 확인)
- `frontend/src/components/review/LazyReviewImage.tsx` 등 이미지 URL 사용처 (확장자 가정 없는지 확인만)

## 범위

- 수정: 위 backend 파일들 + `backend/app/services/settings_service.py`(설정 키 추가), `backend/app/schemas/settings.py`
- 신규/수정 테스트: `backend/tests/` 하위 관련 테스트
- 금지: frontend 수정(확인만, 수정 필요하면 보고), docs/, 그 외 backend

## 구현

1. 설정 키 `generation_image_format`(기본 `"webp"`, `"png"` 허용)과 `generation_webp_quality`(기본 92, 1~100) 추가. settings_service의 public settings에 노출 + setter.
2. 저장 지점에서 NAIA가 준 PNG 바이트를 PIL로 열어 WebP로 저장:
   - `image.save(path, "WEBP", quality=<설정값>, method=6)` — 해상도 변경 금지, RGBA면 RGBA 유지(WebP 알파 지원)
   - 파일 확장자 `.webp`, `image_path` DB 값도 `.webp`
   - `generation_image_format="png"`이면 기존 동작 유지 (폴백 경로)
3. 썸네일 생성(media.py)이 소스 확장자와 무관하게 동작하도록 확인/수정. 썸네일 출력 포맷도 WebP로 (기존이 JPEG/PNG라면 WebP로 전환하되 URL 규약이 확장자를 포함하면 호환 유지 방안을 판단해 보고).
4. FileResponse/StaticFiles mimetype이 `.webp` → `image/webp`로 나가는지 확인 (Windows 레지스트리 의존 이슈 있으면 명시적 media_type 지정).
5. catalog_selected 이동·삭제 로직이 확장자 하드코딩 없이 동작하는지 확인/수정.
6. 품질 파라미터 근거: 원본 대비 시각 무손실에 가까우면서 용량 최소가 목표. quality=92/method=6이 일반적으로 PNG 대비 70~85% 절감. 더 나은 판단(예: 95)이 있으면 근거와 함께 조정 가능.

## 테스트

- 저장 유닛 테스트: PNG 바이트 입력 → `.webp` 파일 생성, 해상도 동일, 파일 크기 < PNG, PIL로 재오픈 가능
- format="png" 폴백 동작
- 썸네일 생성이 webp 소스에서 동작

## 완료 기준

- `../.venv/Scripts/python.exe -m pytest tests/ -q --basetemp=.pytest_tmp_f10 -p no:cacheprovider` 관련 테스트 통과 (기존 실패 3종 제외: test_db_write_queue, test_series_merge_service, test_wiki_and_membership)
- 실제 DB·output 무변경, git commit 금지
- 변경 파일·품질 파라미터 판단 근거·frontend 수정 필요 여부 보고
