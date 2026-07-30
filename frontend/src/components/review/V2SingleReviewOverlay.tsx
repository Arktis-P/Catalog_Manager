import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api } from "../../api/client";
import type {
  V2ReviewCharacter,
  V2ReviewFilters,
  V2ReviewReferenceItem,
  V2ReviewReferenceImagesResponse,
} from "../../types";
import { cycleGender } from "../../utils/reviewPrompt";
import { pendingReviewImageUrl, referenceReviewImageUrl } from "../../utils/reviewImages";
import {
  identityDotTitle,
  qualityDotTitle,
  statusDotClass,
  V2ReviewRow,
  type V2CharacterDraft,
  type V2ReviewCardSaveStatus,
} from "./V2ReviewRow";

const PRELOAD_PREVIOUS = 5;
const PRELOAD_NEXT = 20;
const PRELOAD_CONCURRENCY = 3;

type ReferenceCacheEntry =
  | { status: "loading" }
  | { status: "loaded"; response: V2ReviewReferenceImagesResponse }
  | { status: "error"; message: string };

interface V2SingleReviewOverlayProps {
  open: boolean;
  item: V2ReviewCharacter;
  rowIndex: number;
  globalIndex: number;
  total: number;
  draft: V2CharacterDraft;
  thumbSize: number;
  filters: V2ReviewFilters;
  locked: boolean;
  saveStatus: V2ReviewCardSaveStatus;
  regenerateMessage?: string;
  regenerateProgress?: { current: number; total: number } | null;
  regenerating: boolean;
  suspended?: boolean;
  onClose: () => void;
  onNavigateLocal: (direction: 1 | -1) => boolean;
  onNavigatePage: (direction: 1 | -1) => void;
  onDraftChange: (draft: V2CharacterDraft) => void;
  onToggleTag: (tagKey: string) => void;
  onRate: (value: number) => void;
  onCycleMulticolor: () => void;
  onRegenerate: () => void;
  onComplete: () => void;
  onBulkComplete: () => void;
  onOpenLinkModal: () => void;
}

function sourceLabel(source: V2ReviewReferenceItem["source"]): string {
  return source === "wiki_sample" ? "WIKI" : "FAV";
}

function isEditableTarget(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) {
    return false;
  }
  const tag = target.tagName.toLowerCase();
  return tag === "input" || tag === "textarea" || tag === "select" || target.isContentEditable;
}

function readPixelValue(value: string): number {
  const parsed = Number.parseFloat(value);
  return Number.isFinite(parsed) ? parsed : 0;
}

function ReferenceSlot({
  index,
  item,
  loading,
  error,
  onOpen,
}: {
  index: number;
  item: V2ReviewReferenceItem | null;
  loading: boolean;
  error: string | null;
  onOpen: (item: V2ReviewReferenceItem) => void;
}) {
  const [imageFailed, setImageFailed] = useState(false);

  if (item) {
    const thumbUrl = referenceReviewImageUrl(item.thumbnail_url) ?? referenceReviewImageUrl(item.preview_url);
    return (
      <button className="v2-single-reference-slot" type="button" onClick={() => onOpen(item)}>
        {thumbUrl && !imageFailed ? (
          <img
            src={thumbUrl}
            alt={`reference ${index + 1}`}
            loading="lazy"
            decoding="async"
            onError={() => setImageFailed(true)}
          />
        ) : (
          <span className="v2-single-reference-image-error">Image error</span>
        )}
        <span className={`v2-single-reference-badge v2-single-reference-badge--${item.source}`}>
          {sourceLabel(item.source)}
        </span>
      </button>
    );
  }

  return (
    <div className="v2-single-reference-slot v2-single-reference-slot--empty">
      <span>{loading ? "Loading" : error ? "Error" : "Empty"}</span>
    </div>
  );
}

export function V2SingleReviewOverlay({
  open,
  item,
  rowIndex,
  globalIndex,
  total,
  draft,
  thumbSize,
  filters,
  locked,
  saveStatus,
  regenerateMessage,
  regenerateProgress,
  regenerating,
  suspended = false,
  onClose,
  onNavigateLocal,
  onNavigatePage,
  onDraftChange,
  onToggleTag,
  onRate,
  onCycleMulticolor,
  onRegenerate,
  onComplete,
  onBulkComplete,
  onOpenLinkModal,
}: V2SingleReviewOverlayProps) {
  const [, setCacheVersion] = useState(0);
  const overlayRef = useRef<HTMLDivElement>(null);
  const cacheRef = useRef<Map<number, ReferenceCacheEntry>>(new Map());
  const generationRef = useRef(0);
  const rangeVersionRef = useRef(0);
  const allowedIdsRef = useRef<Set<number>>(new Set());
  const requestControllersRef = useRef<Map<number, AbortController>>(new Map());
  const [previewItem, setPreviewItem] = useState<V2ReviewReferenceItem | null>(null);
  const [generatedPreviewOpen, setGeneratedPreviewOpen] = useState(false);
  const currentImage = item.images[draft.imageIndex] ?? null;
  const currentImageUrl = currentImage ? pendingReviewImageUrl(currentImage.image_path) : null;
  const activeReference = cacheRef.current.get(item.id);
  const activeReferences = activeReference?.status === "loaded" ? activeReference.response.items.slice(0, 5) : [];
  const referenceError = activeReference?.status === "error" ? activeReference.message : null;
  const referenceLoading = !activeReference || activeReference.status === "loading";

  const preloadFilters = useMemo(
    () => {
      const previousCount = Math.min(PRELOAD_PREVIOUS, globalIndex);
      return {
        ...filters,
        review_status: "pending" as const,
        skip: globalIndex - previousCount,
        limit: previousCount + 1 + PRELOAD_NEXT,
      };
    },
    [filters, globalIndex],
  );

  const bumpCache = useCallback(() => setCacheVersion((version) => version + 1), []);

  useEffect(() => {
    if (!open) {
      return;
    }

    let frameId = 0;
    const overlay = overlayRef.current;
    const host =
      overlay?.closest<HTMLElement>(".review-page") ??
      document.querySelector<HTMLElement>(".review-page") ??
      null;
    const pageContainer =
      host?.closest<HTMLElement>(".page-container") ??
      document.querySelector<HTMLElement>(".page-container") ??
      null;
    const appBody = document.querySelector<HTMLElement>(".app-body");
    const observed = [host, pageContainer, appBody].filter((node): node is HTMLElement => Boolean(node));

    const measure = () => {
      frameId = 0;
      const visibleHost = host ?? pageContainer ?? appBody;
      if (!visibleHost) {
        return;
      }

      const hostRect = visibleHost.getBoundingClientRect();
      const pageRect = pageContainer?.getBoundingClientRect() ?? hostRect;
      const bodyRect = appBody?.getBoundingClientRect() ?? pageRect;
      const pageStyles = pageContainer ? window.getComputedStyle(pageContainer) : null;
      const inlineInset = pageStyles
        ? Math.max(8, Math.min(24, readPixelValue(pageStyles.paddingLeft), readPixelValue(pageStyles.paddingRight)))
        : 12;
      const bottomInset = pageStyles ? Math.max(8, Math.min(24, readPixelValue(pageStyles.paddingBottom))) : 12;

      const left = Math.max(0, bodyRect.left, pageRect.left, hostRect.left);
      const top = Math.max(0, bodyRect.top, pageRect.top, hostRect.top);
      const right = Math.min(window.innerWidth, bodyRect.right, pageRect.right, hostRect.right);
      const bottom = Math.min(window.innerHeight, bodyRect.bottom, pageRect.bottom, hostRect.bottom) - bottomInset;
      const width = Math.max(280, Math.floor(right - left - inlineInset));
      const height = Math.max(320, Math.floor(bottom - top));
      const nextLeft = Math.round(left);
      const nextTop = Math.round(top);

      if (overlay) {
        overlay.style.left = `${nextLeft}px`;
        overlay.style.top = `${nextTop}px`;
        overlay.style.width = `${width}px`;
        overlay.style.height = `${height}px`;
        overlay.style.visibility = "visible";
      }

    };

    const scheduleMeasure = () => {
      if (frameId) {
        return;
      }
      frameId = window.requestAnimationFrame(measure);
    };

    scheduleMeasure();
    window.addEventListener("resize", scheduleMeasure);
    pageContainer?.addEventListener("scroll", scheduleMeasure, { passive: true });

    const resizeObserver =
      typeof ResizeObserver === "undefined"
        ? null
        : new ResizeObserver(() => {
            scheduleMeasure();
          });
    for (const node of observed) {
      resizeObserver?.observe(node);
    }

    return () => {
      if (frameId) {
        window.cancelAnimationFrame(frameId);
      }
      window.removeEventListener("resize", scheduleMeasure);
      pageContainer?.removeEventListener("scroll", scheduleMeasure);
      resizeObserver?.disconnect();
    };
  }, [open]);

  const ensureReference = useCallback(
    async (characterId: number, generation: number, rangeVersion: number) => {
      if (
        generationRef.current !== generation ||
        rangeVersionRef.current !== rangeVersion ||
        !allowedIdsRef.current.has(characterId)
      ) {
        return;
      }
      const existing = cacheRef.current.get(characterId);
      if (existing?.status === "loading" || existing?.status === "loaded") {
        return;
      }
      cacheRef.current.set(characterId, { status: "loading" });
      const controller = new AbortController();
      requestControllersRef.current.set(characterId, controller);
      bumpCache();
      try {
        const response = await api.getV2ReviewReferenceImages(characterId, { signal: controller.signal });
        if (
          generationRef.current !== generation ||
          rangeVersionRef.current !== rangeVersion ||
          !allowedIdsRef.current.has(characterId)
        ) {
          return;
        }
        cacheRef.current.set(characterId, { status: "loaded", response });
      } catch (err) {
        if (
          generationRef.current !== generation ||
          rangeVersionRef.current !== rangeVersion ||
          !allowedIdsRef.current.has(characterId)
        ) {
          return;
        }
        cacheRef.current.set(characterId, {
          status: "error",
          message: err instanceof Error ? err.message : "Reference lookup failed",
        });
      } finally {
        if (requestControllersRef.current.get(characterId) === controller) {
          requestControllersRef.current.delete(characterId);
        }
        if (
          generationRef.current === generation &&
          rangeVersionRef.current === rangeVersion &&
          allowedIdsRef.current.has(characterId)
        ) {
          bumpCache();
        }
      }
    },
    [bumpCache],
  );

  useEffect(() => {
    if (!open) {
      return;
    }
    const generation = generationRef.current + 1;
    generationRef.current = generation;
    cacheRef.current.clear();
    allowedIdsRef.current = new Set([item.id]);
    setPreviewItem(null);
    setGeneratedPreviewOpen(false);
    bumpCache();

    return () => {
      for (const controller of requestControllersRef.current.values()) {
        controller.abort();
      }
      requestControllersRef.current.clear();
      generationRef.current += 1;
      rangeVersionRef.current += 1;
      allowedIdsRef.current.clear();
      cacheRef.current.clear();
    };
    // The overlay is unmounted on close. Filters changing also closes it in the parent.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  useEffect(() => {
    if (!open) {
      return;
    }
    const generation = generationRef.current;
    const rangeVersion = rangeVersionRef.current + 1;
    rangeVersionRef.current = rangeVersion;
    for (const controller of requestControllersRef.current.values()) {
      controller.abort();
    }
    requestControllersRef.current.clear();
    allowedIdsRef.current = new Set([item.id]);
    for (const [characterId, entry] of Array.from(cacheRef.current.entries())) {
      if (entry.status === "loading") {
        cacheRef.current.delete(characterId);
      }
    }
    bumpCache();

    let cancelled = false;
    void (async () => {
      const currentRequest = ensureReference(item.id, generation, rangeVersion);
      try {
        const response = await api.listV2ReviewCharacters(preloadFilters);
        if (
          cancelled ||
          generationRef.current !== generation ||
          rangeVersionRef.current !== rangeVersion
        ) {
          return;
        }
        const currentIndex = response.items.findIndex((entry) => entry.id === item.id);
        const ordered = [
          ...(currentIndex >= 0 ? [response.items[currentIndex]] : [item]),
          ...(currentIndex >= 0 ? response.items.slice(currentIndex + 1) : response.items.filter((entry) => entry.id !== item.id)),
          ...(currentIndex > 0 ? response.items.slice(0, currentIndex) : []),
        ];
        const allowedIds = new Set(ordered.map((entry) => entry.id));
        allowedIds.add(item.id);
        allowedIdsRef.current = allowedIds;
        for (const characterId of Array.from(cacheRef.current.keys())) {
          if (!allowedIds.has(characterId)) {
            cacheRef.current.delete(characterId);
          }
        }
        bumpCache();
        let cursor = 0;
        const workers = Array.from({ length: Math.max(1, PRELOAD_CONCURRENCY - 1) }, async () => {
          while (!cancelled && generationRef.current === generation && cursor < ordered.length) {
            const next = ordered[cursor];
            cursor += 1;
            await ensureReference(next.id, generation, rangeVersion);
          }
        });
        await Promise.all([currentRequest, ...workers]);
      } catch {
        await currentRequest;
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [bumpCache, ensureReference, item, open, preloadFilters]);

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (!open || suspended) {
        return;
      }
      event.stopPropagation();
      event.stopImmediatePropagation();
      if (event.key === "Escape") {
        event.preventDefault();
        if (previewItem) {
          setPreviewItem(null);
        } else if (generatedPreviewOpen) {
          setGeneratedPreviewOpen(false);
        } else {
          onClose();
        }
        return;
      }
      if (previewItem || generatedPreviewOpen) {
        event.preventDefault();
        return;
      }
      if (isEditableTarget(event.target)) {
        return;
      }
      if (event.ctrlKey && event.key === "Enter") {
        event.preventDefault();
        onBulkComplete();
        return;
      }
      const key = event.key.toLowerCase();
      if (locked) {
        const allowed =
          event.key === "ArrowLeft" ||
          event.key === "ArrowRight" ||
          key === "q" ||
          key === "w" ||
          key === "a";
        if (!allowed) {
          event.preventDefault();
          return;
        }
      }
      if (event.key === " " || event.code === "Space") {
        event.preventDefault();
        if (currentImageUrl) {
          setGeneratedPreviewOpen((current) => !current);
        }
        return;
      }
      if (event.key === "Enter") {
        event.preventDefault();
        onComplete();
        return;
      }
      if (event.ctrlKey && event.key >= "1" && event.key <= "9") {
        event.preventDefault();
        const imageIndex = Number(event.key) - 1;
        if (imageIndex < item.images.length) {
          onDraftChange({ ...draft, imageIndex });
        }
        return;
      }
      if (event.key === "ArrowLeft") {
        event.preventDefault();
        if (!onNavigateLocal(-1)) {
          onNavigatePage(-1);
        }
        return;
      }
      if (event.key === "ArrowRight") {
        event.preventDefault();
        if (!onNavigateLocal(1)) {
          onNavigatePage(1);
        }
        return;
      }
      if (event.key >= "0" && event.key <= "6") {
        event.preventDefault();
        onRate(Number(event.key));
        return;
      }
      if (key === "z" && !event.ctrlKey && !event.metaKey && !event.altKey) {
        event.preventDefault();
        onRate(0);
        return;
      }
      if (event.key === "-" || (key === "x" && !event.ctrlKey && !event.metaKey && !event.altKey)) {
        event.preventDefault();
        onRate(-1);
        return;
      }
      if (key === "g") {
        event.preventDefault();
        onDraftChange({ ...draft, gender: cycleGender(draft.gender) });
        return;
      }
      if (key === "c") {
        event.preventDefault();
        onCycleMulticolor();
        return;
      }
      if (key === "r") {
        event.preventDefault();
        onRegenerate();
        return;
      }
      if (key === "w") {
        event.preventDefault();
        window.open(
          item.danbooru_wiki_url ||
            `https://danbooru.donmai.us/wiki_pages/${encodeURIComponent(item.character_tag)}`,
          "_blank",
          "noopener,noreferrer",
        );
        return;
      }
      if (key === "q") {
        event.preventDefault();
        window.open(
          `https://danbooru.donmai.us/posts?tags=${encodeURIComponent(
            `${item.character_tag} ${item.series_tags[0] ?? ""}`.trim(),
          )}`,
          "_blank",
          "noopener,noreferrer",
        );
        return;
      }
      if (key === "a") {
        event.preventDefault();
        onOpenLinkModal();
      }
    };
    window.addEventListener("keydown", onKeyDown, { capture: true });
    return () => window.removeEventListener("keydown", onKeyDown, { capture: true });
  }, [
    item,
    currentImageUrl,
    draft,
    generatedPreviewOpen,
    locked,
    onBulkComplete,
    onClose,
    onComplete,
    onNavigateLocal,
    onNavigatePage,
    onCycleMulticolor,
    onDraftChange,
    onOpenLinkModal,
    onRate,
    onRegenerate,
    open,
    previewItem,
    suspended,
  ]);

  const slots = Array.from({ length: 5 }, (_, index) => activeReferences[index] ?? null);
  const previewUrl =
    referenceReviewImageUrl(previewItem?.preview_url) ?? referenceReviewImageUrl(previewItem?.thumbnail_url);
  const wikiReferenceCount = activeReferences.filter((reference) => reference.source === "wiki_sample").length;
  const favoriteReferenceCount = activeReferences.length - wikiReferenceCount;
  const referenceSummary = referenceLoading
    ? "Loading"
    : referenceError
      ? "Lookup failed"
      : activeReferences.length === 0
        ? "레퍼런스 없음"
        : wikiReferenceCount === 0
          ? `Wiki Sample 없음 · favorite ${favoriteReferenceCount}/5`
          : activeReferences.length < 5
            ? `일부만 존재 ${activeReferences.length}/5`
            : favoriteReferenceCount > 0
              ? `Wiki ${wikiReferenceCount} · Favorite ${favoriteReferenceCount}`
              : "Wiki 5/5";

  return (
    <div ref={overlayRef} className="v2-single-overlay" role="dialog" aria-modal="true" aria-label="단일 항목 보기">
      <div className="v2-single-toolbar">
        <div>
          <strong>{item.display_name || item.character_tag}</strong>
          <span className="catalog-card-subtitle"> {globalIndex + 1}/{total}</span>
        </div>
        <div className="v2-single-toolbar-actions">
          <button className="btn btn-small" type="button" onClick={() => (onNavigateLocal(-1) ? undefined : onNavigatePage(-1))}>
            이전
          </button>
          <button className="btn btn-small" type="button" onClick={() => (onNavigateLocal(1) ? undefined : onNavigatePage(1))}>
            다음
          </button>
          <button className="btn btn-small" type="button" onClick={onClose}>
            닫기
          </button>
        </div>
      </div>

      <div className="v2-single-layout">
        <section className="v2-single-generated-pane" aria-label="generated image">
          <div className="v2-single-generated-frame">
            {currentImageUrl ? (
              <img src={currentImageUrl} alt={`${item.character_tag} generated`} />
            ) : (
              <span className="review-image-placeholder">No image</span>
            )}
            {regenerating ? (
              <div className="v2-single-regenerating-overlay">
                <span>{regenerateMessage ?? "Regenerating"}</span>
                {regenerateProgress ? (
                  <span>{regenerateProgress.current}/{regenerateProgress.total}</span>
                ) : null}
              </div>
            ) : null}
            {currentImage ? (
              <div className="v2-single-generated-status">
                <span className={statusDotClass(currentImage.quality_status)} title={qualityDotTitle(currentImage)} />
                <span className={statusDotClass(currentImage.identity_status)} title={identityDotTitle(currentImage)} />
                {currentImage.is_provisional ? <span className="badge badge-warning">임시 대표</span> : null}
              </div>
            ) : null}
          </div>
          {item.images.length > 1 ? (
            <div className="v2-single-image-selector">
              {item.images.map((_, index) => (
                <button
                  key={index}
                  type="button"
                  className={`v2-review-card-image-chip${index === draft.imageIndex ? " v2-review-card-image-chip--active" : ""}`}
                  disabled={locked}
                  onClick={() => onDraftChange({ ...draft, imageIndex: index })}
                >
                  {index + 1}
                </button>
              ))}
            </div>
          ) : null}
          <div className="catalog-card-subtitle">{saveStatus.label}{saveStatus.detail ? ` - ${saveStatus.detail}` : ""}</div>
        </section>

        <section className="v2-single-detail-pane" aria-label="review controls">
          <div className="v2-single-row-host">
            <V2ReviewRow
              item={item}
              rowIndex={rowIndex}
              focused
              draft={draft}
              thumbSize={thumbSize}
              locked={locked}
              saveStatus={saveStatus}
              regenerateMessage={regenerateMessage}
              regenerateProgress={regenerateProgress}
              onDraftChange={onDraftChange}
              onToggleTag={onToggleTag}
              onRate={onRate}
              onRegenerate={onRegenerate}
              onComplete={onComplete}
              onOpenLinkModal={onOpenLinkModal}
              regenerating={regenerating}
            />
          </div>

        </section>

        <div className="v2-single-reference-panel">
          <div className="v2-single-reference-header">
            <strong>Reference Images</strong>
            <span className="catalog-card-subtitle">{referenceSummary}</span>
          </div>
          {referenceError ? <div className="v2-single-reference-error">{referenceError}</div> : null}
          <div className="v2-single-reference-grid">
            {slots.map((slot, index) => (
              <ReferenceSlot
                key={slot ? slot.post_id : `empty-${index}`}
                index={index}
                item={slot}
                loading={referenceLoading}
                error={referenceError}
                onOpen={setPreviewItem}
              />
            ))}
          </div>
        </div>
      </div>

      {previewItem ? (
        <div className="v2-single-reference-preview" role="dialog" aria-modal="true" aria-label="reference preview">
          <div className="v2-single-reference-preview-box">
            <div className="v2-single-reference-preview-actions">
              <a className="btn btn-small" href={previewItem.post_url} target="_blank" rel="noreferrer">
                Original post
              </a>
              <button className="btn btn-small" type="button" onClick={() => setPreviewItem(null)}>
                Close
              </button>
            </div>
            {previewUrl ? <img src={previewUrl} alt="reference preview" /> : <div className="empty-state">No preview</div>}
          </div>
        </div>
      ) : null}

      {generatedPreviewOpen && currentImageUrl ? (
        <div className="v2-single-reference-preview" role="dialog" aria-modal="true" aria-label="generated image preview">
          <div className="v2-single-reference-preview-box">
            <div className="v2-single-reference-preview-actions">
              <button className="btn btn-small" type="button" onClick={() => setGeneratedPreviewOpen(false)}>
                Close
              </button>
            </div>
            <img src={currentImageUrl} alt={`${item.character_tag} generated preview`} />
          </div>
        </div>
      ) : null}
    </div>
  );
}
