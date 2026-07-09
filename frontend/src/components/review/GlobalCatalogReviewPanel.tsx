import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../../api/client";
import { CharacterLinkModal } from "../CharacterLinkModal";
import { useReviewRegenerateJobs } from "../../context/ReviewRegenerateContext";
import type { CatalogReviewFilterStatus, CatalogReviewItem, LinkableCharacterSummary } from "../../types";
import { danbooruPostsUrl, danbooruWikiUrl, openExternal } from "../../utils/danbooruLinks";
import {
  appearanceTagChips,
  cycleGender,
  defaultEnabledTagKeys,
  resolveFinalPrompt,
  selectedTagsPayload,
} from "../../utils/reviewPrompt";
import { pendingReviewImageUrl } from "../../utils/reviewImages";
import { CatalogReviewRow, createDraftForItem, type CharacterDraft } from "./CatalogReviewRow";
import { ReviewImagePreview } from "./ReviewImagePreview";
import { toggleRating } from "./ReviewRatingStars";
import { ReviewShortcutGuide } from "./ReviewShortcutGuide";

const PAGE_SIZE = 30;
const PREVIEW_SIZE = 600;
const PREVIEW_GAP = 8;

function isEditableTarget(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) {
    return false;
  }
  const tag = target.tagName.toLowerCase();
  return tag === "input" || tag === "textarea" || tag === "select" || target.isContentEditable;
}

function toLinkableSummary(item: CatalogReviewItem): LinkableCharacterSummary {
  return {
    id: item.id,
    character_tag: item.character_tag,
    display_name: item.display_name,
    is_alternative: Boolean(item.is_alternative),
    parent_character_tag: item.parent_character_tag ?? null,
    parent_display_name: item.parent_display_name ?? null,
    child_count: item.child_count ?? 0,
  };
}

interface GlobalCatalogReviewPanelProps {
  initialCharacterId?: number | null;
}

export function GlobalCatalogReviewPanel({ initialCharacterId = null }: GlobalCatalogReviewPanelProps) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const [items, setItems] = useState<CatalogReviewItem[]>([]);
  const [total, setTotal] = useState(0);
  const [filterStatus, setFilterStatus] = useState<CatalogReviewFilterStatus>(
    initialCharacterId ? "all" : "pending",
  );
  const [search, setSearch] = useState("");
  const [skip, setSkip] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [actionMessage, setActionMessage] = useState<string | null>(null);
  const [focusIndex, setFocusIndex] = useState(0);
  const [drafts, setDrafts] = useState<Record<number, CharacterDraft>>({});
  const [submittingId, setSubmittingId] = useState<number | null>(null);
  const [bulkPurging, setBulkPurging] = useState(false);
  const [thumbSize, setThumbSize] = useState(384);
  const [quadLayout, setQuadLayout] = useState(false);
  const [previewOpen, setPreviewOpen] = useState(false);
  const [previewPosition, setPreviewPosition] = useState<{ top: number; left: number } | null>(null);
  const [linkingItem, setLinkingItem] = useState<CatalogReviewItem | null>(null);
  const [pendingCharacterId, setPendingCharacterId] = useState<number | null>(initialCharacterId);
  const appliedRegenerateJobIdsRef = useRef<Set<string>>(new Set());

  const {
    enqueueRegenerateGlobal,
    isCharacterRegenerating,
    getCharacterJob,
    lastCompletedJob,
    clearLastCompletedJob,
    lastError: regenerateError,
    clearLastError: clearRegenerateError,
  } = useReviewRegenerateJobs();

  useEffect(() => {
    void api.getSettings().then((settings) => {
      setThumbSize(settings.review_thumbnail_size);
      setQuadLayout(settings.generation_images_per_character > 2);
    });
  }, []);

  const loadReviews = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const response = await api.listCatalogReviewsGlobal({
        filter_status: filterStatus,
        search: search || undefined,
        skip,
        limit: PAGE_SIZE,
      });
      setItems(response.items);
      setTotal(response.total);
      let nextFocus = 0;
      if (pendingCharacterId) {
        const found = response.items.findIndex((item) => item.id === pendingCharacterId);
        if (found >= 0) {
          nextFocus = found;
        }
        setPendingCharacterId(null);
      }
      setFocusIndex(nextFocus);
      setDrafts(Object.fromEntries(response.items.map((item) => [item.id, createDraftForItem(item)])));
    } catch (err) {
      setError(err instanceof Error ? err.message : "카탈로그 검수 목록을 불러오지 못했습니다.");
    } finally {
      setLoading(false);
    }
  }, [filterStatus, search, skip]);

  useEffect(() => {
    void loadReviews();
  }, [loadReviews]);

  useEffect(() => {
    setSkip(0);
  }, [filterStatus, search]);

  const updateDraft = (characterId: number, draft: CharacterDraft) => {
    setDrafts((current) => ({ ...current, [characterId]: draft }));
  };

  const toggleTag = (characterId: number, tagKey: string) => {
    const item = items.find((entry) => entry.id === characterId);
    if (!item) return;
    const current = drafts[characterId] ?? createDraftForItem(item);
    const enabled = new Set(
      current.enabledTags.size > 0 ? current.enabledTags : defaultEnabledTagKeys(appearanceTagChips(item)),
    );
    if (enabled.has(tagKey)) {
      enabled.delete(tagKey);
    } else {
      enabled.add(tagKey);
    }
    updateDraft(characterId, { ...current, enabledTags: enabled });
  };

  const setRating = (characterId: number, value: number) => {
    const item = items.find((entry) => entry.id === characterId);
    if (!item) return;
    const current = drafts[characterId] ?? createDraftForItem(item);
    updateDraft(characterId, { ...current, rating: toggleRating(current.rating, value) });
  };

  const completeItem = async (item: CatalogReviewItem) => {
    const draft = drafts[item.id] ?? createDraftForItem(item);
    const isRatingZero = draft.rating === 0 || draft.rating === -1;
    const image = item.images[draft.imageIndex];
    if (!isRatingZero && !image) {
      setActionMessage("선택할 이미지가 없습니다.");
      return;
    }
    const chips = appearanceTagChips(item);
    const enabledTags = draft.enabledTags.size > 0 ? draft.enabledTags : defaultEnabledTagKeys(chips);
    const finalPrompt = resolveFinalPrompt(item, { ...draft, enabledTags });

    setSubmittingId(item.id);
    setError(null);
    try {
      await api.completeCatalogReviewGlobal(item.id, {
        cover_image_id: isRatingZero ? null : image!.id,
        gender: draft.gender,
        rating: draft.rating,
        final_prompt: finalPrompt,
        selected_tags: isRatingZero ? null : selectedTagsPayload(item, enabledTags),
      });
      setActionMessage(`${item.character_tag} 완료`);
      await loadReviews();
    } catch (err) {
      setError(err instanceof Error ? err.message : "검수 완료에 실패했습니다.");
    } finally {
      setSubmittingId(null);
    }
  };

  const undoItem = async (item: CatalogReviewItem) => {
    setSubmittingId(item.id);
    setError(null);
    try {
      await api.undoCatalogReviewGlobal(item.id);
      setActionMessage(`${item.character_tag} 되돌림`);
      await loadReviews();
    } catch (err) {
      setError(err instanceof Error ? err.message : "실행 취소에 실패했습니다.");
    } finally {
      setSubmittingId(null);
    }
  };

  const handlePurgeUnselected = async (item: CatalogReviewItem) => {
    if (!window.confirm(`${item.character_tag}의 선택되지 않은 이미지를 삭제할까요? 되돌릴 수 없습니다.`)) {
      return;
    }
    setSubmittingId(item.id);
    setError(null);
    try {
      const response = await api.purgeUnselectedCatalogImagesGlobal(item.id);
      setItems((current) => current.map((entry) => (entry.id === item.id ? response.item : entry)));
      setActionMessage(`${item.character_tag} 미선택 이미지 ${response.removed_count}장 삭제됨`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "미선택 이미지 삭제에 실패했습니다.");
    } finally {
      setSubmittingId(null);
    }
  };

  const handlePurgeUnselectedAll = async () => {
    const targets = items.filter((item) => item.review_status === "completed" && item.images.length > 1);
    if (targets.length === 0) {
      setActionMessage("삭제할 미선택 이미지가 있는 항목이 없습니다.");
      return;
    }
    if (
      !window.confirm(
        `현재 화면에 로드된 ${targets.length}개 항목의 선택되지 않은 이미지를 모두 삭제할까요? 되돌릴 수 없습니다.`,
      )
    ) {
      return;
    }
    setBulkPurging(true);
    setError(null);
    let removedTotal = 0;
    try {
      for (const item of targets) {
        const response = await api.purgeUnselectedCatalogImagesGlobal(item.id);
        removedTotal += response.removed_count;
        setItems((current) => current.map((entry) => (entry.id === item.id ? response.item : entry)));
      }
      setActionMessage(`${targets.length}개 항목에서 미선택 이미지 ${removedTotal}장 삭제됨`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "미선택 이미지 일괄 삭제에 실패했습니다.");
    } finally {
      setBulkPurging(false);
    }
  };

  const mergeRegeneratedItem = useCallback((updated: CatalogReviewItem) => {
    setItems((current) => current.map((entry) => (entry.id === updated.id ? updated : entry)));
    setDrafts((current) => {
      const preserved = current[updated.id];
      const nextDraft = createDraftForItem(updated);
      if (preserved) {
        nextDraft.rating = preserved.rating;
        nextDraft.gender = preserved.gender;
        nextDraft.enabledTags = preserved.enabledTags;
        nextDraft.customPrompt = preserved.customPrompt;
        nextDraft.promptEdited = preserved.promptEdited;
      }
      nextDraft.imageIndex = 0;
      return { ...current, [updated.id]: nextDraft };
    });
  }, []);

  useEffect(() => {
    if (!lastCompletedJob?.result || lastCompletedJob.scope !== "global") {
      return;
    }
    if (appliedRegenerateJobIdsRef.current.has(lastCompletedJob.job_id)) {
      return;
    }
    appliedRegenerateJobIdsRef.current.add(lastCompletedJob.job_id);
    mergeRegeneratedItem(lastCompletedJob.result);
    setActionMessage(
      `${lastCompletedJob.character_tag} 이미지 ${lastCompletedJob.result.images.length}장 재생성 완료 (기존 이미지 교체됨)`,
    );
    clearLastCompletedJob();
  }, [clearLastCompletedJob, lastCompletedJob, mergeRegeneratedItem]);

  useEffect(() => {
    if (regenerateError) {
      setError(regenerateError);
      clearRegenerateError();
    }
  }, [clearRegenerateError, regenerateError]);

  const focusedItem = items[focusIndex] ?? null;
  const focusedDraft = focusedItem ? drafts[focusedItem.id] ?? createDraftForItem(focusedItem) : null;
  const focusedLocked = focusedItem
    ? submittingId === focusedItem.id || isCharacterRegenerating(focusedItem.id, "global")
    : false;
  const focusedImage = focusedItem?.images[focusedDraft?.imageIndex ?? 0] ?? null;
  const previewSrc = focusedImage
    ? pendingReviewImageUrl(focusedImage.image_path, { thumbnail: true, thumbSize: PREVIEW_SIZE })
    : null;
  const previewAlt = focusedItem ? `${focusedItem.character_tag} preview` : "";

  useEffect(() => {
    if (!focusedItem || !previewSrc) {
      setPreviewOpen(false);
    }
  }, [focusedItem, previewSrc]);

  useEffect(() => {
    if (focusedLocked) {
      setPreviewOpen(false);
    }
  }, [focusedLocked]);

  const togglePreview = useCallback(() => {
    if (focusedLocked) {
      return;
    }
    setPreviewOpen((open) => {
      if (open) {
        return false;
      }
      return Boolean(previewSrc);
    });
  }, [focusedLocked, previewSrc]);

  const updatePreviewPosition = useCallback(() => {
    const scrollNode = scrollRef.current;
    if (!scrollNode || !focusedItem) {
      setPreviewPosition(null);
      return;
    }
    // 개별 썸네일이 아니라 포커스된 행 전체를 기준으로 삼아, 미리보기가 항상
    // 행의 왼쪽(좌측 작업 목록 사이드바 쪽)으로만 확장되고 현재 행의 썸네일/
    // 정보(aside)는 절대 가리지 않도록 한다.
    const row = scrollNode.querySelector(`[data-character-id="${focusedItem.id}"]`) as HTMLElement | null;
    if (!row) {
      setPreviewPosition(null);
      return;
    }
    const rect = row.getBoundingClientRect();
    let top = rect.top + rect.height / 2 - PREVIEW_SIZE / 2;
    let left = rect.left - PREVIEW_GAP - PREVIEW_SIZE;
    left = Math.max(PREVIEW_GAP, Math.min(left, window.innerWidth - PREVIEW_SIZE - PREVIEW_GAP));
    top = Math.max(PREVIEW_GAP, Math.min(top, window.innerHeight - PREVIEW_SIZE - PREVIEW_GAP));
    setPreviewPosition({ top, left });
  }, [focusedItem]);

  useEffect(() => {
    if (!previewOpen) {
      setPreviewPosition(null);
      return;
    }
    const frame = window.requestAnimationFrame(() => updatePreviewPosition());
    const scrollNode = scrollRef.current;
    const onReposition = () => updatePreviewPosition();
    window.addEventListener("resize", onReposition);
    scrollNode?.addEventListener("scroll", onReposition, { passive: true });
    return () => {
      window.cancelAnimationFrame(frame);
      window.removeEventListener("resize", onReposition);
      scrollNode?.removeEventListener("scroll", onReposition);
    };
  }, [previewOpen, previewSrc, focusIndex, updatePreviewPosition]);

  const shiftFocusedImage = useCallback(
    (delta: -1 | 1) => {
      if (!focusedItem || !focusedDraft || focusedLocked) {
        return;
      }
      const maxIndex = Math.max(0, focusedItem.images.length - 1);
      const nextIndex = Math.min(maxIndex, Math.max(0, focusedDraft.imageIndex + delta));
      updateDraft(focusedItem.id, { ...focusedDraft, imageIndex: nextIndex });
    },
    [focusedDraft, focusedItem, focusedLocked],
  );

  const regenerateFocused = useCallback(async () => {
    if (!focusedItem || !focusedDraft) {
      return;
    }
    const chips = appearanceTagChips(focusedItem);
    const enabledTags = focusedDraft.enabledTags.size > 0 ? focusedDraft.enabledTags : defaultEnabledTagKeys(chips);
    const finalPrompt = resolveFinalPrompt(focusedItem, { ...focusedDraft, enabledTags });
    if (!finalPrompt?.trim()) {
      setError("프롬프트가 비어 있어 재생성할 수 없습니다.");
      return;
    }
    setError(null);
    try {
      const job = await enqueueRegenerateGlobal(focusedItem.id, {
        prompt: finalPrompt,
        gender: focusedDraft.gender,
      });
      setPreviewOpen(false);
      setActionMessage(job.message);
    } catch (err) {
      setError(err instanceof Error ? err.message : "재생성에 실패했습니다.");
      setActionMessage(null);
    }
  }, [enqueueRegenerateGlobal, focusedDraft, focusedItem]);

  useEffect(() => {
    const node = scrollRef.current;
    if (!node || !focusedItem) {
      return;
    }
    const row = node.querySelector(`[data-character-id="${focusedItem.id}"]`);
    row?.scrollIntoView({ block: "nearest" });
  }, [focusIndex, focusedItem]);

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (isEditableTarget(event.target) || !focusedItem || !focusedDraft) {
        return;
      }

      if (focusedLocked) {
        const key = event.key.toLowerCase();
        const allowed =
          event.key === "ArrowUp" || event.key === "ArrowDown" || key === "q" || key === "w" || key === "a";
        if (!allowed) {
          event.preventDefault();
          return;
        }
      }

      if (event.key === " " || event.code === "Space") {
        event.preventDefault();
        event.stopPropagation();
        togglePreview();
        return;
      }

      if (event.key === "ArrowLeft") {
        event.preventDefault();
        shiftFocusedImage(-1);
        return;
      }

      if (event.key === "ArrowRight") {
        event.preventDefault();
        shiftFocusedImage(1);
        return;
      }

      if (event.key === "ArrowUp") {
        event.preventDefault();
        setFocusIndex((index) => Math.max(0, index - 1));
        return;
      }

      if (event.key === "ArrowDown") {
        event.preventDefault();
        setFocusIndex((index) => Math.min(items.length - 1, index + 1));
        return;
      }

      if (event.key >= "0" && event.key <= "6") {
        event.preventDefault();
        setRating(focusedItem.id, Number(event.key));
        return;
      }

      if (event.key === "-") {
        event.preventDefault();
        setRating(focusedItem.id, -1);
        return;
      }

      if (event.key === "Enter") {
        event.preventDefault();
        void completeItem(focusedItem);
        return;
      }

      const key = event.key.toLowerCase();
      if (key === "g") {
        event.preventDefault();
        updateDraft(focusedItem.id, { ...focusedDraft, gender: cycleGender(focusedDraft.gender) });
        return;
      }
      if (key === "r") {
        event.preventDefault();
        void regenerateFocused();
        return;
      }
      if (key === "q") {
        event.preventDefault();
        openExternal(danbooruPostsUrl(focusedItem.character_tag, focusedItem.series_tag, focusedItem.danbooru_url));
        return;
      }
      if (key === "w") {
        event.preventDefault();
        openExternal(danbooruWikiUrl(focusedItem.character_tag, focusedItem.danbooru_wiki_url));
        return;
      }
      if (key === "a") {
        event.preventDefault();
        setLinkingItem(focusedItem);
      }
    };

    window.addEventListener("keydown", onKeyDown, { capture: true });
    return () => window.removeEventListener("keydown", onKeyDown, { capture: true });
  }, [focusedDraft, focusedItem, focusedLocked, items.length, regenerateFocused, shiftFocusedImage, togglePreview]);

  const pageCount = Math.max(1, Math.ceil(total / PAGE_SIZE));
  const currentPage = Math.floor(skip / PAGE_SIZE) + 1;

  return (
    <>
      <div className="toolbar review-toolbar">
        <div className="field">
          <label htmlFor="global-catalog-review-filter">Filter</label>
          <select
            id="global-catalog-review-filter"
            value={filterStatus}
            onChange={(event) => setFilterStatus(event.target.value as CatalogReviewFilterStatus)}
          >
            <option value="pending">Pending</option>
            <option value="completed">Completed</option>
            <option value="all">All with images</option>
          </select>
        </div>
        <div className="field">
          <label htmlFor="global-catalog-review-search">Search</label>
          <input
            id="global-catalog-review-search"
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            placeholder="character tag"
          />
        </div>
        <div className="field" style={{ justifyContent: "flex-end" }}>
          <label>&nbsp;</label>
          <button className="btn" type="button" onClick={() => void loadReviews()}>
            Refresh
          </button>
        </div>
        <div className="field" style={{ justifyContent: "flex-end" }}>
          <label>&nbsp;</label>
          <button
            className="btn"
            type="button"
            onClick={() => void handlePurgeUnselectedAll()}
            disabled={bulkPurging || items.length === 0}
            title="현재 화면에 로드된 항목들의 선택되지 않은 이미지를 모두 삭제합니다."
          >
            미선택 이미지 전체 삭제
          </button>
        </div>
        <ReviewShortcutGuide includeMerge />
      </div>

      <div className="catalog-review-progress">
        {items.length.toLocaleString()} / {total.toLocaleString()} 표시 · 페이지 {currentPage}/{pageCount}
        {focusedItem ? ` · focus: ${focusedItem.character_tag}` : ""}
      </div>

      {error ? <div className="error-banner">{error}</div> : null}
      {actionMessage ? <div className="catalog-card-subtitle" style={{ marginBottom: 8 }}>{actionMessage}</div> : null}

      {loading ? (
        <div className="empty-state">Loading catalog reviews...</div>
      ) : items.length === 0 ? (
        <div className="empty-state panel">검수할 캐릭터가 없습니다. (특징 태그 수집 완료 후 이미지 생성이 필요합니다)</div>
      ) : (
        <div ref={scrollRef} className="catalog-review-scroll" style={{ overflowY: "auto" }}>
          {items.map((item, rowIndex) => {
            const draft = drafts[item.id] ?? createDraftForItem(item);
            const focused = rowIndex === focusIndex;
            const locked = submittingId === item.id || isCharacterRegenerating(item.id, "global");
            const regenerateJob = getCharacterJob(item.id, "global");
            return (
              <div
                key={item.id}
                className="global-catalog-review-row-wrapper"
                onMouseDown={() => setFocusIndex(rowIndex)}
              >
                <CatalogReviewRow
                  item={item}
                  rowIndex={rowIndex}
                  focused={focused}
                  draft={draft}
                  thumbSize={thumbSize}
                  quadLayout={quadLayout}
                  locked={locked}
                  regenerateMessage={regenerateJob?.message}
                  regenerateProgress={
                    regenerateJob && regenerateJob.total > 0
                      ? { current: regenerateJob.current, total: regenerateJob.total }
                      : null
                  }
                  onDraftChange={(next) => updateDraft(item.id, next)}
                  onToggleTag={(tagKey) => toggleTag(item.id, tagKey)}
                  onRate={(value) => setRating(item.id, value)}
                  onRegenerate={focused ? () => void regenerateFocused() : undefined}
                  onComplete={() => void completeItem(item)}
                  onPurgeUnselected={() => void handlePurgeUnselected(item)}
                  onOpenLinkModal={() => setLinkingItem(item)}
                  regenerating={locked}
                />
                <div className="global-catalog-review-row-actions">
                  {item.review_status === "completed" ? (
                    <button
                      className="btn btn-small"
                      type="button"
                      disabled={locked}
                      onClick={() => void undoItem(item)}
                    >
                      되돌리기
                    </button>
                  ) : null}
                </div>
              </div>
            );
          })}
        </div>
      )}

      {previewOpen && previewSrc ? (
        <ReviewImagePreview
          src={previewSrc}
          alt={previewAlt}
          top={previewPosition?.top ?? PREVIEW_GAP}
          left={previewPosition?.left ?? PREVIEW_GAP}
        />
      ) : null}

      {linkingItem ? (
        <CharacterLinkModal
          character={toLinkableSummary(linkingItem)}
          onClose={() => setLinkingItem(null)}
          onLinked={() => void loadReviews()}
        />
      ) : null}

      {total > PAGE_SIZE ? (
        <div className="series-pagination">
          <div className="series-pagination-controls">
            <button className="btn btn-small" type="button" disabled={skip === 0} onClick={() => setSkip(0)}>«</button>
            <button
              className="btn btn-small"
              type="button"
              disabled={skip === 0}
              onClick={() => setSkip((s) => Math.max(0, s - PAGE_SIZE))}
            >
              ‹
            </button>
            <span className="series-pagination-page-total">{currentPage} / {pageCount}</span>
            <button
              className="btn btn-small"
              type="button"
              disabled={currentPage >= pageCount}
              onClick={() => setSkip((s) => s + PAGE_SIZE)}
            >
              ›
            </button>
          </div>
        </div>
      ) : null}
    </>
  );
}
