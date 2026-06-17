import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api } from "../../api/client";
import type { CatalogReviewItem, Series } from "../../types";
import { danbooruPostsUrl, danbooruWikiUrl, openExternal } from "../../utils/danbooruLinks";
import { appearanceTagChips, defaultEnabledTagKeys, resolveFinalPrompt } from "../../utils/reviewPrompt";
import { pendingReviewImageUrl } from "../../utils/reviewImages";
import { SeriesSearchSelect } from "../SeriesSearchSelect";
import { CatalogReviewRow, createDraftForItem, type CharacterDraft } from "./CatalogReviewRow";
import { ReviewImagePreview } from "./ReviewImagePreview";
import { ReviewMoveSeriesModal } from "./ReviewMoveSeriesModal";
import { toggleRating } from "./ReviewRatingStars";

const ROW_HEIGHT = 296;
const ROW_HEIGHT_QUAD = 448;
const ROW_GAP = 12;
const PAGE_SIZE = 50;
const PREVIEW_SIZE = 600;
const PREVIEW_GAP = 8;

function isEditableTarget(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) {
    return false;
  }
  const tag = target.tagName.toLowerCase();
  return tag === "input" || tag === "textarea" || tag === "select" || target.isContentEditable;
}

function reviewProgressKey(seriesId: number): string {
  return `catalog-review-progress-${seriesId}`;
}

interface CatalogReviewPanelProps {
  initialSeriesId?: number | "";
  initialCharacterId?: number | null;
}

export function CatalogReviewPanel({ initialSeriesId = "", initialCharacterId = null }: CatalogReviewPanelProps) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const [selectedSeriesId, setSelectedSeriesId] = useState<number | "">(initialSeriesId);
  const [selectedSeries, setSelectedSeries] = useState<Series | null>(null);
  const [items, setItems] = useState<CatalogReviewItem[]>([]);
  const [total, setTotal] = useState(0);
  const [filterStatus, setFilterStatus] = useState<"pending" | "completed" | "all" | "needs_check">("pending");
  const [search, setSearch] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [actionMessage, setActionMessage] = useState<string | null>(null);
  const [focusIndex, setFocusIndex] = useState(0);
  const [scrollTop, setScrollTop] = useState(0);
  const [viewportHeight, setViewportHeight] = useState(640);
  const [drafts, setDrafts] = useState<Record<number, CharacterDraft>>({});
  const [undoStack, setUndoStack] = useState<number[]>([]);
  const [submitting, setSubmitting] = useState(false);
  const [previewOpen, setPreviewOpen] = useState(false);
  const [previewPosition, setPreviewPosition] = useState<{ top: number; left: number } | null>(null);
  const [thumbSize, setThumbSize] = useState(384);
  const [maxLoadedImages, setMaxLoadedImages] = useState(30);
  const [imagesPerCharacter, setImagesPerCharacter] = useState(2);
  const [moveTarget, setMoveTarget] = useState<CatalogReviewItem | null>(null);
  const [sessionCompleted, setSessionCompleted] = useState(0);
  const [pendingCharacterId, setPendingCharacterId] = useState<number | null>(initialCharacterId);

  const quadLayout = imagesPerCharacter > 2;
  const rowHeight = quadLayout ? ROW_HEIGHT_QUAD : ROW_HEIGHT;
  const rowStride = rowHeight + ROW_GAP;

  const focusedItem = items[focusIndex] ?? null;
  const focusedDraft = focusedItem ? drafts[focusedItem.id] ?? createDraftForItem(focusedItem) : null;
  const focusedImage = focusedItem?.images[focusedDraft?.imageIndex ?? 0] ?? null;
  const previewSrc = focusedImage ? pendingReviewImageUrl(focusedImage.image_path) : null;
  const previewAlt = focusedItem ? `${focusedItem.character_tag} preview` : "";

  useEffect(() => {
    void api.getSettings().then((settings) => {
      setThumbSize(settings.review_thumbnail_size);
      setMaxLoadedImages(settings.review_max_loaded_images);
      setImagesPerCharacter(settings.generation_images_per_character);
    });
  }, []);

  useEffect(() => {
    if (!initialSeriesId) {
      return;
    }
    void api.listSeries({ limit: 1, search: undefined }).then(() => {
      void api.listSeries({ sort_by: "post_count", sort_order: "desc", limit: 500 }).then((response) => {
        const series = response.items.find((entry) => entry.id === initialSeriesId);
        if (series) {
          setSelectedSeries(series);
        }
      });
    });
  }, [initialSeriesId]);

  const loadReviews = useCallback(async () => {
    if (!selectedSeriesId) {
      setItems([]);
      setTotal(0);
      return;
    }

    setLoading(true);
    setError(null);
    try {
      const response = await api.listCatalogReviews({
        series_id: selectedSeriesId,
        filter_status: filterStatus,
        search: search || undefined,
        skip: 0,
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
      } else if (selectedSeriesId) {
        const saved = localStorage.getItem(reviewProgressKey(selectedSeriesId));
        if (saved) {
          try {
            const parsed = JSON.parse(saved) as { characterId?: number };
            if (parsed.characterId) {
              const found = response.items.findIndex((item) => item.id === parsed.characterId);
              if (found >= 0) {
                nextFocus = found;
              }
            }
          } catch {
            // ignore invalid saved progress
          }
        }
      }
      setFocusIndex(nextFocus);
      setDrafts(
        Object.fromEntries(response.items.map((item) => [item.id, createDraftForItem(item)])),
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : "카탈로그 검수 목록을 불러오지 못했습니다.");
    } finally {
      setLoading(false);
    }
  }, [filterStatus, search, selectedSeriesId]);

  useEffect(() => {
    void loadReviews();
  }, [loadReviews]);

  useEffect(() => {
    const node = scrollRef.current;
    if (!node) {
      return;
    }

    const onScroll = () => setScrollTop(node.scrollTop);
    const resize = () => setViewportHeight(node.clientHeight);
    resize();
    node.addEventListener("scroll", onScroll, { passive: true });
    window.addEventListener("resize", resize);
    return () => {
      node.removeEventListener("scroll", onScroll);
      window.removeEventListener("resize", resize);
    };
  }, [items.length]);

  const scrollToRow = useCallback((index: number) => {
    const node = scrollRef.current;
    if (!node) {
      return;
    }
    const top = index * rowStride;
    const bottom = top + rowHeight;
    if (top < node.scrollTop) {
      node.scrollTop = top;
    } else if (bottom > node.scrollTop + node.clientHeight) {
      node.scrollTop = bottom - node.clientHeight;
    }
  }, [rowHeight, rowStride]);

  useEffect(() => {
    if (!selectedSeriesId || !focusedItem) {
      return;
    }
    localStorage.setItem(
      reviewProgressKey(selectedSeriesId),
      JSON.stringify({ characterId: focusedItem.id, filterStatus }),
    );
  }, [filterStatus, focusedItem, selectedSeriesId]);

  const updateDraft = useCallback((characterId: number, draft: CharacterDraft) => {
    setDrafts((current) => ({ ...current, [characterId]: draft }));
  }, []);

  const toggleTag = useCallback(
    (characterId: number, tagKey: string) => {
      const item = items.find((entry) => entry.id === characterId);
      if (!item) {
        return;
      }
      const current = drafts[characterId] ?? createDraftForItem(item);
      const enabled = new Set(current.enabledTags.size > 0 ? current.enabledTags : defaultEnabledTagKeys(appearanceTagChips(item)));
      if (enabled.has(tagKey)) {
        enabled.delete(tagKey);
      } else {
        enabled.add(tagKey);
      }
      updateDraft(characterId, {
        ...current,
        enabledTags: enabled,
        customPrompt: current.promptEdited ? current.customPrompt : null,
        promptEdited: current.promptEdited,
      });
    },
    [drafts, items, updateDraft],
  );

  const removeCharacterFromList = useCallback((characterId: number) => {
    setItems((current) => {
      const next = current.filter((entry) => entry.id !== characterId);
      setFocusIndex((index) => Math.min(index, Math.max(0, next.length - 1)));
      return next;
    });
    setTotal((count) => Math.max(0, count - 1));
    setPreviewOpen(false);
  }, []);

  const handleDismissNeedsCheck = useCallback(async (item: CatalogReviewItem) => {
    setSubmitting(true);
    setError(null);
    try {
      await api.dismissCatalogNeedsCheck(item.id);
      setItems((current) =>
        current.map((entry) =>
          entry.id === item.id ? { ...entry, character_status: "confirmed", needs_check_reason: null } : entry,
        ),
      );
      setActionMessage(`${item.character_tag} 소속을 확정했습니다.`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "소속 확정에 실패했습니다.");
    } finally {
      setSubmitting(false);
    }
  }, []);

  const handleDeleteCharacter = useCallback(
    async (item: CatalogReviewItem) => {
      if (!window.confirm(`${item.character_tag} 캐릭터를 삭제할까요?`)) {
        return;
      }
      setSubmitting(true);
      setError(null);
      try {
        await api.deleteCharacter(item.id);
        removeCharacterFromList(item.id);
        setActionMessage(`${item.character_tag} 삭제됨`);
      } catch (err) {
        setError(err instanceof Error ? err.message : "캐릭터 삭제에 실패했습니다.");
      } finally {
        setSubmitting(false);
      }
    },
    [removeCharacterFromList],
  );

  const handleMoveSeries = useCallback(
    async (item: CatalogReviewItem, seriesId: number) => {
      await api.updateCharacterSeries(item.id, seriesId);
      removeCharacterFromList(item.id);
      setActionMessage(`${item.character_tag} 시리즈 이동 완료`);
    },
    [removeCharacterFromList],
  );

  const completeFocused = useCallback(async () => {
    if (!focusedItem || !focusedDraft || submitting) {
      return;
    }

    const image = focusedItem.images[focusedDraft.imageIndex];
    if (!image) {
      setActionMessage("선택할 이미지가 없습니다.");
      return;
    }

    const chips = appearanceTagChips(focusedItem);
    const enabledTags =
      focusedDraft.enabledTags.size > 0 ? focusedDraft.enabledTags : defaultEnabledTagKeys(chips);
    const finalPrompt = resolveFinalPrompt(focusedItem, {
      ...focusedDraft,
      enabledTags,
    });

    setSubmitting(true);
    setError(null);
    try {
      await api.completeCatalogReview(focusedItem.id, {
        cover_image_id: image.id,
        gender: focusedDraft.gender,
        rating: focusedDraft.rating,
        final_prompt: finalPrompt,
      });
      setUndoStack((stack) => [focusedItem.id, ...stack].slice(0, 20));
      setItems((current) => {
        if (filterStatus === "pending") {
          const next = current.filter((entry) => entry.id !== focusedItem.id);
          setFocusIndex((index) => Math.min(index, Math.max(0, next.length - 1)));
          return next;
        }
        return current.map((entry) =>
          entry.id === focusedItem.id
            ? {
                ...entry,
                review_status: "completed",
                cover_image_id: image.id,
                rating: focusedDraft.rating,
                gender: focusedDraft.gender,
                final_prompt: finalPrompt,
              }
            : entry,
        );
      });
      setTotal((count) => (filterStatus === "pending" ? Math.max(0, count - 1) : count));
      setSessionCompleted((count) => count + 1);
      setPreviewOpen(false);
      setActionMessage(`${focusedItem.character_tag} 완료`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "검수 완료에 실패했습니다.");
    } finally {
      setSubmitting(false);
    }
  }, [filterStatus, focusedDraft, focusedItem, submitting]);

  const undoLast = useCallback(async () => {
    const characterId = undoStack[0];
    if (!characterId || submitting) {
      return;
    }

    setSubmitting(true);
    setError(null);
    try {
      await api.undoCatalogReview(characterId);
      setUndoStack((stack) => stack.slice(1));
      await loadReviews();
      setActionMessage("이전 선택을 취소했습니다.");
    } catch (err) {
      setError(err instanceof Error ? err.message : "실행 취소에 실패했습니다.");
    } finally {
      setSubmitting(false);
    }
  }, [loadReviews, submitting, undoStack]);

  const setRating = useCallback(
    (characterId: number, value: number) => {
      const item = items.find((entry) => entry.id === characterId);
      if (!item) {
        return;
      }
      const current = drafts[characterId] ?? createDraftForItem(item);
      updateDraft(characterId, {
        ...current,
        rating: toggleRating(current.rating, value),
      });
    },
    [drafts, items, updateDraft],
  );

  const regenerateFocused = useCallback(async () => {
    if (!focusedItem || submitting) {
      return;
    }

    setSubmitting(true);
    setError(null);
    try {
      await api.regenerateCatalogCharacter(focusedItem.id);
      setActionMessage(`${focusedItem.character_tag} 재생성을 시작했습니다.`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "재생성 요청에 실패했습니다.");
    } finally {
      setSubmitting(false);
    }
  }, [focusedItem, submitting]);

  useEffect(() => {
    if (!focusedItem || !previewSrc) {
      setPreviewOpen(false);
    }
  }, [focusedItem, previewSrc]);

  const updatePreviewPosition = useCallback(() => {
    if (!previewOpen || !scrollRef.current) {
      setPreviewPosition(null);
      return;
    }

    const anchor = scrollRef.current.querySelector('[data-preview-anchor="true"]') as HTMLElement | null;
    if (!anchor) {
      setPreviewPosition(null);
      return;
    }

    const rect = anchor.getBoundingClientRect();
    let top = rect.top - PREVIEW_SIZE - PREVIEW_GAP;
    let left = rect.left + rect.width / 2 - PREVIEW_SIZE / 2;

    if (top < PREVIEW_GAP) {
      top = rect.bottom + PREVIEW_GAP;
    }

    left = Math.max(PREVIEW_GAP, Math.min(left, window.innerWidth - PREVIEW_SIZE - PREVIEW_GAP));
    top = Math.max(PREVIEW_GAP, Math.min(top, window.innerHeight - PREVIEW_SIZE - PREVIEW_GAP));

    setPreviewPosition({ top, left });
  }, [rowHeight, rowStride]);

  useEffect(() => {
    if (!previewOpen) {
      setPreviewPosition(null);
      return;
    }

    const frame = window.requestAnimationFrame(() => {
      updatePreviewPosition();
    });

    const scrollNode = scrollRef.current;
    const onReposition = () => updatePreviewPosition();
    window.addEventListener("resize", onReposition);
    scrollNode?.addEventListener("scroll", onReposition, { passive: true });

    return () => {
      window.cancelAnimationFrame(frame);
      window.removeEventListener("resize", onReposition);
      scrollNode?.removeEventListener("scroll", onReposition);
    };
  }, [previewOpen, previewSrc, focusIndex, focusedDraft?.imageIndex, updatePreviewPosition]);

  const togglePreview = useCallback(() => {
    if (previewOpen) {
      setPreviewOpen(false);
      return;
    }
    if (previewSrc) {
      setPreviewOpen(true);
    }
  }, [previewOpen, previewSrc]);

  const shiftFocusedImage = useCallback(
    (delta: -1 | 1) => {
      if (!focusedItem || !focusedDraft) {
        return;
      }
      const maxIndex = Math.max(0, focusedItem.images.length - 1);
      const nextIndex = Math.min(maxIndex, Math.max(0, focusedDraft.imageIndex + delta));
      updateDraft(focusedItem.id, { ...focusedDraft, imageIndex: nextIndex });
    },
    [focusedDraft, focusedItem, updateDraft],
  );

  useEffect(() => {
    scrollToRow(focusIndex);
  }, [focusIndex, scrollToRow]);

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (isEditableTarget(event.target) || !focusedItem || !focusedDraft) {
        return;
      }

      if (event.key === " " || event.code === "Space") {
        event.preventDefault();
        event.stopPropagation();
        togglePreview();
        return;
      }

      if (event.ctrlKey && event.key.toLowerCase() === "z") {
        event.preventDefault();
        void undoLast();
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
        void completeFocused();
        return;
      }

      const key = event.key.toLowerCase();
      if (key === "g") {
        event.preventDefault();
        updateDraft(focusedItem.id, { ...focusedDraft, gender: "1girl" });
        return;
      }
      if (key === "b") {
        event.preventDefault();
        updateDraft(focusedItem.id, { ...focusedDraft, gender: "1boy" });
        return;
      }
      if (key === "n") {
        event.preventDefault();
        updateDraft(focusedItem.id, { ...focusedDraft, gender: "no_humans" });
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
      }
    };

    window.addEventListener("keydown", onKeyDown, { capture: true });
    return () => window.removeEventListener("keydown", onKeyDown, { capture: true });
  }, [
    completeFocused,
    focusedDraft,
    focusedItem,
    items.length,
    regenerateFocused,
    setRating,
    shiftFocusedImage,
    togglePreview,
    undoLast,
    updateDraft,
  ]);

  const virtualRange = useMemo(() => {
    const imagesPerRow = quadLayout ? 4 : 2;
    const maxRows = Math.max(1, Math.ceil(maxLoadedImages / imagesPerRow));
    const visibleRows = Math.max(1, Math.ceil(viewportHeight / rowStride));
    const overscan = Math.max(1, Math.floor((maxRows - visibleRows) / 2));
    const start = Math.max(0, Math.floor(scrollTop / rowStride) - overscan);
    const visibleCount = visibleRows + overscan * 2;
    const end = Math.min(items.length, start + visibleCount);
    return { start, end };
  }, [items.length, maxLoadedImages, quadLayout, rowStride, scrollTop, viewportHeight]);

  const totalHeight = Math.max(0, items.length * rowStride - ROW_GAP);

  return (
    <>
      <div className="toolbar review-toolbar">
        <div className="field review-series-field">
          <label>Series</label>
          <SeriesSearchSelect
            value={selectedSeriesId}
            onChange={(seriesId, series) => {
              setSelectedSeriesId(seriesId);
              setSelectedSeries(series ?? null);
            }}
          />
        </div>
        <div className="field">
          <label htmlFor="catalog-review-filter">Filter</label>
          <select
            id="catalog-review-filter"
            value={filterStatus}
            onChange={(event) => setFilterStatus(event.target.value as typeof filterStatus)}
          >
            <option value="pending">Pending</option>
            <option value="completed">Completed</option>
            <option value="all">All with images</option>
            <option value="needs_check">needs_check</option>
          </select>
        </div>
        <div className="field">
          <label htmlFor="catalog-review-search">Search</label>
          <input
            id="catalog-review-search"
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            placeholder="character tag"
          />
        </div>
        <div className="field" style={{ justifyContent: "flex-end" }}>
          <label>&nbsp;</label>
          <button className="btn" type="button" onClick={() => void loadReviews()} disabled={!selectedSeriesId}>
            Refresh
          </button>
        </div>
      </div>

      <div className="review-shortcut-bar">
        <span className="review-rating-guide-inline">
          평점: -1 대상 아님 · 0 생성 불가 · 1~2 보통 · 3 잠재 · 4 검증 · 5~6 선호
        </span>
        <span>←→ 이미지</span>
        <span>↑↓ 캐릭터</span>
        <span>0-6 / - 레이팅 (재입력 시 해제)</span>
        <span>Enter 완료</span>
        <span>g/b/n 성별</span>
        <span>r 재생성</span>
        <span>Ctrl+Z 취소</span>
        <span>q/w Danbooru</span>
        <span>Space 확대</span>
      </div>

      {selectedSeries ? (
        <div className="catalog-review-progress">
          {selectedSeries.display_name || selectedSeries.series_tag} · {items.length.toLocaleString()} /{" "}
          {total.toLocaleString()} 표시
          {focusedItem ? ` · focus: ${focusedItem.character_tag}` : ""}
          {sessionCompleted > 0 ? ` · session ${sessionCompleted} completed` : ""}
        </div>
      ) : null}

      {error ? <div className="error-banner">{error}</div> : null}
      {actionMessage ? <div className="catalog-card-subtitle" style={{ marginBottom: 8 }}>{actionMessage}</div> : null}

      {!selectedSeriesId ? (
        <div className="empty-state panel">검수할 시리즈를 선택하세요.</div>
      ) : loading ? (
        <div className="empty-state">Loading catalog reviews...</div>
      ) : items.length === 0 ? (
        <div className="empty-state panel">검수할 캐릭터가 없습니다.</div>
      ) : (
        <div ref={scrollRef} className="catalog-review-scroll" tabIndex={-1}>
          <div className="catalog-review-virtual-spacer" style={{ height: totalHeight }}>
            <div
              className="catalog-review-virtual-window"
              style={{ transform: `translateY(${virtualRange.start * rowStride}px)` }}
            >
              {items.slice(virtualRange.start, virtualRange.end).map((item, offset) => {
                const rowIndex = virtualRange.start + offset;
                const draft = drafts[item.id] ?? createDraftForItem(item);
                return (
                  <CatalogReviewRow
                    key={item.id}
                    item={item}
                    rowIndex={rowIndex}
                    focused={rowIndex === focusIndex}
                    draft={draft}
                    thumbSize={thumbSize}
                    quadLayout={quadLayout}
                    onDraftChange={(next) => updateDraft(item.id, next)}
                    onToggleTag={(tagKey) => toggleTag(item.id, tagKey)}
                    onRate={(value) => setRating(item.id, value)}
                    onDismissNeedsCheck={
                      item.character_status === "needs_check"
                        ? () => void handleDismissNeedsCheck(item)
                        : undefined
                    }
                    onDeleteCharacter={() => void handleDeleteCharacter(item)}
                    onMoveSeries={
                      item.character_status === "needs_check" ? () => setMoveTarget(item) : undefined
                    }
                  />
                );
              })}
            </div>
          </div>
        </div>
      )}

      {previewOpen && previewSrc && previewPosition ? (
        <ReviewImagePreview src={previewSrc} alt={previewAlt} top={previewPosition.top} left={previewPosition.left} />
      ) : null}

      {moveTarget ? (
        <ReviewMoveSeriesModal
          characterTag={moveTarget.character_tag}
          currentSeriesTag={moveTarget.series_tag}
          onClose={() => setMoveTarget(null)}
          onConfirm={(seriesId) => handleMoveSeries(moveTarget, seriesId)}
        />
      ) : null}
    </>
  );
}
