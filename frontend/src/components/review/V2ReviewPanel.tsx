import { useCallback, useEffect, useMemo, useRef, useState, type CSSProperties } from "react";
import { api } from "../../api/client";
import { CharacterLinkModal } from "../CharacterLinkModal";
import { SeriesSearchSelect } from "../SeriesSearchSelect";
import type { LinkableCharacterSummary, Series, V2GenerationJobState, V2ReviewCharacter, V2ReviewStats } from "../../types";
import { cycleGender, defaultEnabledTagKeys } from "../../utils/reviewPrompt";
import { pendingReviewImageUrl } from "../../utils/reviewImages";
import {
  getV2ReviewCardSize,
  getV2ReviewCardWidthPx,
  onV2ReviewCardSettingsChanged,
  resolveV2ReviewCardWidthPx,
  type V2ReviewCardSize,
} from "../../utils/v2ReviewCardSettings";
import {
  createV2DraftForItem,
  resolveV2FinalPrompt,
  v2AppearanceTagChips,
  v2SelectedTagsPayload,
  V2ReviewRow,
  type V2CharacterDraft,
} from "./V2ReviewRow";
import { ReviewImagePreview } from "./ReviewImagePreview";
import { toggleRating } from "./ReviewRatingStars";
import { ReviewShortcutGuide } from "./ReviewShortcutGuide";

const PAGE_SIZE = 30;

const V2_RATING_FLOW: Array<{ question: string; result: string }> = [
  { question: "사람 또는 고정된 사람형 캐릭터가 아닌가요? (고정 외형 없는 플레이어 대리 캐릭터 포함)", result: "-1" },
  { question: "레이팅 가능한 이미지 생성에 실패했나요?", result: "0" },
  { question: "boy 캐릭터의 특성이 여전히 강한가요?", result: "1" },
  { question: "완전히 기피하고 싶은 태그가 있나요?", result: "2" },
  { question: "그 외 여성 캐릭터인가요? (기본값)", result: "3" },
  { question: "확실한 고선호인가요? (정말 좋아함 / 최선호)", result: "5 / 6" },
];

function V2RatingGuide() {
  return (
    <details className="review-rating-guide">
      <summary className="review-rating-guide-summary">
        <span className="review-rating-guide-title">V2 1차 레이팅 가이드</span>
        <span className="review-rating-guide-hint">-1/0/1/2/3/5/6 권장 · 4는 1차 리뷰에서 사용하지 않음</span>
      </summary>
      <div className="review-rating-guide-body">
        <ol className="v2-rating-guide-list">
          {V2_RATING_FLOW.map((row) => (
            <li key={row.question}>
              {row.question} <strong>→ {row.result}</strong>
            </li>
          ))}
        </ol>
      </div>
    </details>
  );
}

function isEditableTarget(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) {
    return false;
  }
  const tag = target.tagName.toLowerCase();
  return tag === "input" || tag === "textarea" || tag === "select" || target.isContentEditable;
}

function toLinkableSummary(item: V2ReviewCharacter): LinkableCharacterSummary {
  return {
    id: item.id,
    character_tag: item.character_tag,
    display_name: item.display_name,
    is_alternative: item.is_alternative,
    parent_character_tag: item.parent_character_tag,
    parent_display_name: item.parent_display_name,
    child_count: item.child_count,
  };
}

export function V2ReviewPanel() {
  const scrollRef = useRef<HTMLDivElement>(null);
  const [items, setItems] = useState<V2ReviewCharacter[]>([]);
  const [total, setTotal] = useState(0);
  const [stats, setStats] = useState<V2ReviewStats | null>(null);

  const [reviewStatus, setReviewStatus] = useState("pending");
  const [ratingFilter, setRatingFilter] = useState("");
  const [qualityStatus, setQualityStatus] = useState("");
  const [identityStatus, setIdentityStatus] = useState("");
  const [generationStatus, setGenerationStatus] = useState("");
  const [genderFilter, setGenderFilter] = useState("");
  const [seriesId, setSeriesId] = useState<number | "">("");
  const [multicolorFilter, setMulticolorFilter] = useState("");
  const [promptModifiedOnly, setPromptModifiedOnly] = useState(false);
  const [search, setSearch] = useState("");

  const [skip, setSkip] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [actionMessage, setActionMessage] = useState<string | null>(null);
  const [focusIndex, setFocusIndex] = useState(0);
  const [drafts, setDrafts] = useState<Record<number, V2CharacterDraft>>({});
  const [submittingId, setSubmittingId] = useState<number | null>(null);
  const [thumbSize, setThumbSize] = useState(384);
  const [cardSize, setCardSize] = useState<V2ReviewCardSize>("medium");
  const [cardWidthPx, setCardWidthPx] = useState(0);
  const [gridCols, setGridCols] = useState(1);
  const [previewOpen, setPreviewOpen] = useState(false);
  const [previewFit, setPreviewFit] = useState(true);
  const [linkingItem, setLinkingItem] = useState<V2ReviewCharacter | null>(null);
  const [popupOpen, setPopupOpen] = useState(false);
  const [popupIndex, setPopupIndex] = useState(0);
  const [popupPosition, setPopupPosition] = useState<{ top: number; left: number } | null>(null);

  // V2 재생성은 F1이 만든 V2 전용 파이프라인(POST .../v2/characters/{id}/regenerate)만 사용한다.
  // V1 catalog-global 재생성 Job Context(ReviewRegenerateContext)는 CatalogReviewItem 형태를
  // 반환하므로 V2 카드 형태와 맞지 않아 여기서는 쓰지 않는다.
  const [v2Jobs, setV2Jobs] = useState<Record<number, V2GenerationJobState>>({});
  const processedV2JobIdsRef = useRef<Set<string>>(new Set());

  const itemsRef = useRef<V2ReviewCharacter[]>([]);
  useEffect(() => {
    itemsRef.current = items;
  }, [items]);

  const isCharacterRegenerating = useCallback(
    (characterId: number) => {
      const job = v2Jobs[characterId];
      return Boolean(job && (job.status === "queued" || job.status === "running"));
    },
    [v2Jobs],
  );
  const regenCheckRef = useRef(isCharacterRegenerating);
  useEffect(() => {
    regenCheckRef.current = isCharacterRegenerating;
  }, [isCharacterRegenerating]);

  useEffect(() => {
    void api.getSettings().then((settings) => {
      setThumbSize(settings.review_thumbnail_size);
      setCardSize(getV2ReviewCardSize() ?? (settings.v2_review_card_size as V2ReviewCardSize) ?? "medium");
      setCardWidthPx(getV2ReviewCardWidthPx() ?? settings.v2_review_card_width_px ?? 0);
    });
  }, []);

  useEffect(
    () =>
      onV2ReviewCardSettingsChanged(() => {
        setCardSize(getV2ReviewCardSize() ?? "medium");
        setCardWidthPx(getV2ReviewCardWidthPx() ?? 0);
      }),
    [],
  );

  const effectiveCardWidthPx = resolveV2ReviewCardWidthPx(cardSize, cardWidthPx);

  useEffect(() => {
    const node = scrollRef.current;
    if (!node) {
      return;
    }
    const measure = () => {
      const style = window.getComputedStyle(node);
      const cols = style.gridTemplateColumns.split(" ").filter(Boolean).length;
      setGridCols(Math.max(1, cols));
    };
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(node);
    return () => observer.disconnect();
  }, [effectiveCardWidthPx]);

  const loadStats = useCallback(async () => {
    try {
      const response = await api.getV2ReviewStats();
      setStats(response);
    } catch {
      // 진행 통계는 부가 정보이므로 실패해도 목록 조회에 영향을 주지 않는다.
    }
  }, []);

  useEffect(() => {
    void loadStats();
  }, [loadStats]);

  const loadReviews = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const response = await api.listV2ReviewCharacters({
        review_status: reviewStatus || undefined,
        rating: ratingFilter || undefined,
        quality_status: qualityStatus || undefined,
        identity_status: identityStatus || undefined,
        generation_status: generationStatus || undefined,
        gender: genderFilter || undefined,
        series_id: seriesId || undefined,
        multicolor: multicolorFilter || undefined,
        prompt_modified: promptModifiedOnly ? true : undefined,
        search: search || undefined,
        skip,
        limit: PAGE_SIZE,
      });
      // 재생성 진행 중인 항목이 목록 응답에서 일시적으로 빠질 수 있으므로, 재생성이
      // 끝날 때까지 기존 위치에 유지한다.
      const fetchedIds = new Set(response.items.map((item) => item.id));
      const kept = itemsRef.current
        .map((item, index) => ({ item, index }))
        .filter(({ item }) => !fetchedIds.has(item.id) && regenCheckRef.current(item.id));
      const merged = [...response.items];
      for (const { item, index } of kept) {
        merged.splice(Math.min(index, merged.length), 0, item);
      }
      setItems(merged);
      setTotal(response.total);
      setFocusIndex((current) => Math.min(current, Math.max(0, merged.length - 1)));
      setDrafts((current) =>
        Object.fromEntries(merged.map((item) => [item.id, current[item.id] ?? createV2DraftForItem(item)])),
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : "V2 리뷰 목록을 불러오지 못했습니다.");
    } finally {
      setLoading(false);
    }
  }, [
    reviewStatus,
    ratingFilter,
    qualityStatus,
    identityStatus,
    generationStatus,
    genderFilter,
    seriesId,
    multicolorFilter,
    promptModifiedOnly,
    search,
    skip,
  ]);

  useEffect(() => {
    void loadReviews();
  }, [loadReviews]);

  useEffect(() => {
    setSkip(0);
    setFocusIndex(0);
  }, [
    reviewStatus,
    ratingFilter,
    qualityStatus,
    identityStatus,
    generationStatus,
    genderFilter,
    seriesId,
    multicolorFilter,
    promptModifiedOnly,
    search,
  ]);

  const updateDraft = (characterId: number, draft: V2CharacterDraft) => {
    setDrafts((current) => ({ ...current, [characterId]: draft }));
  };

  const toggleTag = (characterId: number, tagKey: string) => {
    const item = items.find((entry) => entry.id === characterId);
    if (!item) return;
    const current = drafts[characterId] ?? createV2DraftForItem(item);
    const chips = v2AppearanceTagChips(item);
    const enabled = new Set(current.enabledTags.size > 0 ? current.enabledTags : defaultEnabledTagKeys(chips));
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
    const current = drafts[characterId] ?? createV2DraftForItem(item);
    updateDraft(characterId, { ...current, rating: toggleRating(current.rating, value) });
  };

  const completeItem = async (item: V2ReviewCharacter) => {
    const draft = drafts[item.id] ?? createV2DraftForItem(item);
    const isRatingZero = draft.rating === 0 || draft.rating === -1;
    const image = item.images[draft.imageIndex];
    if (!isRatingZero && !image) {
      setActionMessage("선택할 이미지가 없습니다.");
      return;
    }
    const chips = v2AppearanceTagChips(item);
    const enabledTags = draft.enabledTags.size > 0 ? draft.enabledTags : defaultEnabledTagKeys(chips);
    const finalPrompt = resolveV2FinalPrompt(item, { ...draft, enabledTags });

    setSubmittingId(item.id);
    setError(null);
    try {
      await api.completeV2ReviewCharacter(item.id, {
        cover_image_id: isRatingZero ? null : image!.id,
        gender: draft.gender,
        rating: draft.rating,
        base_prompt: finalPrompt,
        selected_tags: isRatingZero ? null : v2SelectedTagsPayload(item, enabledTags),
      });
      setActionMessage(`${item.character_tag} 리뷰 완료`);
      await loadReviews();
      await loadStats();
    } catch (err) {
      setError(err instanceof Error ? err.message : "리뷰 완료에 실패했습니다.");
    } finally {
      setSubmittingId(null);
    }
  };

  // V2 응답(quality/identity 상태, image_id 등)으로 해당 카드 하나만 다시 조회해 직접 갱신한다.
  // V1 job의 CatalogReviewItem 변환을 거치지 않는다.
  const refreshSingleCharacter = useCallback(
    async (characterId: number, characterTag: string) => {
      try {
        const response = await api.listV2ReviewCharacters({ search: characterTag, skip: 0, limit: 10 });
        const updated =
          response.items.find((entry) => entry.id === characterId) ??
          response.items.find((entry) => entry.character_tag === characterTag);
        if (!updated) {
          await loadReviews();
          return;
        }
        setItems((current) => current.map((entry) => (entry.id === characterId ? updated : entry)));
        setDrafts((current) => ({ ...current, [characterId]: createV2DraftForItem(updated) }));
      } catch {
        await loadReviews();
      }
    },
    [loadReviews],
  );

  const onV2JobSettled = useCallback(
    async (job: V2GenerationJobState) => {
      if (processedV2JobIdsRef.current.has(job.job_id)) {
        return;
      }
      processedV2JobIdsRef.current.add(job.job_id);
      if (job.status === "failed") {
        setError(job.last_failure_reason || job.message || `${job.current_character_tag} 재생성 실패`);
        return;
      }
      if (job.status !== "completed") {
        return;
      }
      setActionMessage(
        `${job.current_character_tag} 재생성 완료 (품질: ${job.quality_status ?? "-"} · 재현: ${job.identity_status ?? "-"})`,
      );
      if (job.character_id != null) {
        await refreshSingleCharacter(job.character_id, job.current_character_tag);
      }
      await loadStats();
    },
    [loadStats, refreshSingleCharacter],
  );

  const runningV2JobIds = useMemo(
    () =>
      Object.values(v2Jobs)
        .filter((job) => job.status === "queued" || job.status === "running")
        .map((job) => job.job_id),
    [v2Jobs],
  );

  useEffect(() => {
    if (runningV2JobIds.length === 0) {
      return;
    }
    let cancelled = false;
    const poll = async () => {
      try {
        const updates = await Promise.all(runningV2JobIds.map((jobId) => api.getV2GenerationJob(jobId)));
        if (cancelled) return;
        setV2Jobs((current) => {
          const next = { ...current };
          for (const job of updates) {
            if (job.character_id != null) {
              next[job.character_id] = job;
            }
          }
          return next;
        });
        for (const job of updates) {
          if (job.status === "completed" || job.status === "failed" || job.status === "cancelled") {
            void onV2JobSettled(job);
          }
        }
      } catch {
        // 폴링 실패는 무시하고 다음 tick에 재시도한다.
      }
    };
    void poll();
    const timer = window.setInterval(() => void poll(), 800);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [runningV2JobIds.join("|")]);

  const focusedItem = items[focusIndex] ?? null;
  const focusedDraft = focusedItem ? drafts[focusedItem.id] ?? createV2DraftForItem(focusedItem) : null;
  const focusedLocked = focusedItem
    ? submittingId === focusedItem.id || isCharacterRegenerating(focusedItem.id)
    : false;
  const focusedImage = focusedItem?.images[focusedDraft?.imageIndex ?? 0] ?? null;
  const previewSrc = focusedImage ? pendingReviewImageUrl(focusedImage.image_path) : null;
  const previewAlt = focusedItem ? `${focusedItem.character_tag} original` : "";

  const multicolorChips = useMemo(
    () => (focusedItem ? v2AppearanceTagChips(focusedItem).filter((chip) => chip.group === "multi") : []),
    [focusedItem],
  );

  useEffect(() => {
    if (!focusedItem || !previewSrc) {
      setPreviewOpen(false);
    }
  }, [focusedItem, previewSrc]);

  useEffect(() => {
    if (focusedLocked) {
      setPreviewOpen(false);
      setPopupOpen(false);
    }
  }, [focusedLocked]);

  const togglePreview = useCallback(() => {
    if (focusedLocked) {
      return;
    }
    setPopupOpen(false);
    setPreviewOpen((open) => {
      if (open) {
        return false;
      }
      if (previewSrc) {
        setPreviewFit(true);
        return true;
      }
      return false;
    });
  }, [focusedLocked, previewSrc]);

  const updatePopupPosition = useCallback(() => {
    const scrollNode = scrollRef.current;
    if (!scrollNode || !focusedItem) {
      setPopupPosition(null);
      return;
    }
    const row = scrollNode.querySelector(`[data-character-id="${focusedItem.id}"]`) as HTMLElement | null;
    if (!row) {
      setPopupPosition(null);
      return;
    }
    const rect = row.getBoundingClientRect();
    const width = 260;
    let top = rect.top + 32;
    let left = rect.right - width;
    left = Math.max(8, Math.min(left, window.innerWidth - width - 8));
    top = Math.max(8, Math.min(top, window.innerHeight - 320 - 8));
    setPopupPosition({ top, left });
  }, [focusedItem]);

  useEffect(() => {
    if (!popupOpen) {
      setPopupPosition(null);
      return;
    }
    const frame = window.requestAnimationFrame(() => updatePopupPosition());
    const scrollNode = scrollRef.current;
    const onReposition = () => updatePopupPosition();
    window.addEventListener("resize", onReposition);
    scrollNode?.addEventListener("scroll", onReposition, { passive: true });
    return () => {
      window.cancelAnimationFrame(frame);
      window.removeEventListener("resize", onReposition);
      scrollNode?.removeEventListener("scroll", onReposition);
    };
  }, [popupOpen, focusIndex, updatePopupPosition]);

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
    if (isCharacterRegenerating(focusedItem.id)) {
      // 실행 중 중복 재생성 시도는 무시한다.
      return;
    }
    const chips = v2AppearanceTagChips(focusedItem);
    const enabledTags = focusedDraft.enabledTags.size > 0 ? focusedDraft.enabledTags : defaultEnabledTagKeys(chips);
    const finalPrompt = resolveV2FinalPrompt(focusedItem, { ...focusedDraft, enabledTags });
    if (!finalPrompt.trim()) {
      setError("프롬프트가 비어 있어 재생성할 수 없습니다.");
      return;
    }
    setError(null);
    try {
      const job = await api.regenerateV2Character(focusedItem.id, { base_prompt: finalPrompt });
      setV2Jobs((current) => ({ ...current, [focusedItem.id]: job }));
      setPreviewOpen(false);
      setActionMessage(`${focusedItem.character_tag} 재생성 시작`);
    } catch (err) {
      const message = err instanceof Error ? err.message : "재생성에 실패했습니다.";
      if (message.toLowerCase().includes("already in progress")) {
        // 409: 백엔드에서 이미 진행 중으로 판단 - 조용히 무시한다.
        return;
      }
      setError(message);
      setActionMessage(null);
    }
  }, [focusedDraft, focusedItem, isCharacterRegenerating]);

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
      if (linkingItem || isEditableTarget(event.target) || !focusedItem || !focusedDraft) {
        return;
      }

      if (popupOpen) {
        if (event.key === "Escape") {
          event.preventDefault();
          setPopupOpen(false);
          return;
        }
        if (event.key === "ArrowUp") {
          event.preventDefault();
          setPopupIndex((index) => Math.max(0, index - 1));
          return;
        }
        if (event.key === "ArrowDown") {
          event.preventDefault();
          setPopupIndex((index) => Math.min(multicolorChips.length - 1, index + 1));
          return;
        }
        if (event.key === "Enter") {
          event.preventDefault();
          const chip = multicolorChips[popupIndex];
          if (chip) {
            toggleTag(focusedItem.id, chip.key);
          }
          return;
        }
        event.preventDefault();
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
        setFocusIndex((index) => Math.max(0, index - gridCols));
        return;
      }

      if (event.key === "ArrowDown") {
        event.preventDefault();
        setFocusIndex((index) => Math.min(items.length - 1, index + gridCols));
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
      if (key === "c") {
        event.preventDefault();
        setPreviewOpen(false);
        setPopupIndex(0);
        setPopupOpen(true);
        return;
      }
      if (key === "r") {
        event.preventDefault();
        void regenerateFocused();
        return;
      }
      if (key === "q") {
        event.preventDefault();
        window.open(
          `https://danbooru.donmai.us/posts?tags=${encodeURIComponent(
            `${focusedItem.character_tag} ${focusedItem.series_tags[0] ?? ""}`.trim(),
          )}`,
          "_blank",
          "noopener,noreferrer",
        );
        return;
      }
      if (key === "w") {
        event.preventDefault();
        window.open(
          focusedItem.danbooru_wiki_url ||
            `https://danbooru.donmai.us/wiki_pages/${encodeURIComponent(focusedItem.character_tag)}`,
          "_blank",
          "noopener,noreferrer",
        );
        return;
      }
      if (key === "a") {
        event.preventDefault();
        setLinkingItem(focusedItem);
      }
    };

    window.addEventListener("keydown", onKeyDown, { capture: true });
    return () => window.removeEventListener("keydown", onKeyDown, { capture: true });
  }, [
    focusedDraft,
    focusedItem,
    focusedLocked,
    gridCols,
    items.length,
    linkingItem,
    multicolorChips,
    popupIndex,
    popupOpen,
    regenerateFocused,
    shiftFocusedImage,
    togglePreview,
  ]);

  const pageCount = Math.max(1, Math.ceil(total / PAGE_SIZE));
  const currentPage = Math.floor(skip / PAGE_SIZE) + 1;
  const gridStyle = { "--v2-card-width": `${effectiveCardWidthPx}px` } as CSSProperties;

  return (
    <>
      <div className="toolbar review-toolbar">
        <div className="field">
          <label htmlFor="v2-review-status">리뷰 상태</label>
          <select id="v2-review-status" value={reviewStatus} onChange={(event) => setReviewStatus(event.target.value)}>
            <option value="">전체</option>
            <option value="pending">Pending</option>
            <option value="in_progress">In progress</option>
            <option value="completed">Completed</option>
          </select>
        </div>
        <div className="field">
          <label htmlFor="v2-review-rating">레이팅</label>
          <select id="v2-review-rating" value={ratingFilter} onChange={(event) => setRatingFilter(event.target.value)}>
            <option value="">전체</option>
            <option value="unrated">미지정</option>
            {[-1, 0, 1, 2, 3, 4, 5, 6].map((value) => (
              <option key={value} value={String(value)}>
                {value}
              </option>
            ))}
          </select>
        </div>
        <div className="field">
          <label htmlFor="v2-review-quality">품질 상태</label>
          <select
            id="v2-review-quality"
            value={qualityStatus}
            onChange={(event) => setQualityStatus(event.target.value)}
          >
            <option value="">전체</option>
            <option value="pass">Pass</option>
            <option value="warning">Warning</option>
            <option value="reject">Reject</option>
          </select>
        </div>
        <div className="field">
          <label htmlFor="v2-review-identity">재현 상태</label>
          <select
            id="v2-review-identity"
            value={identityStatus}
            onChange={(event) => setIdentityStatus(event.target.value)}
          >
            <option value="">전체</option>
            <option value="pass">Pass</option>
            <option value="warning">Warning</option>
            <option value="reject">Reject</option>
          </select>
        </div>
        <div className="field">
          <label htmlFor="v2-review-generation">생성 상태</label>
          <select
            id="v2-review-generation"
            value={generationStatus}
            onChange={(event) => setGenerationStatus(event.target.value)}
          >
            <option value="">전체</option>
            <option value="not_generated">not_generated</option>
            <option value="generating">generating</option>
            <option value="generated">generated</option>
            <option value="generation_failed">generation_failed</option>
            <option value="likely_untrained">likely_untrained</option>
          </select>
        </div>
        <div className="field">
          <label htmlFor="v2-review-gender">성별</label>
          <select id="v2-review-gender" value={genderFilter} onChange={(event) => setGenderFilter(event.target.value)}>
            <option value="">전체</option>
            <option value="1girl">1girl</option>
            <option value="1boy">1boy</option>
            <option value="no_humans">no_humans</option>
          </select>
        </div>
        <div className="field">
          <label htmlFor="v2-review-multicolor">Multicolor</label>
          <select
            id="v2-review-multicolor"
            value={multicolorFilter}
            onChange={(event) => setMulticolorFilter(event.target.value)}
          >
            <option value="">전체</option>
            <option value="has">보유</option>
            <option value="suggested">추천 있음</option>
          </select>
        </div>
        <div className="field review-series-field">
          <label>시리즈</label>
          <SeriesSearchSelect
            value={seriesId}
            onChange={(id: number | "", _series?: Series | null) => setSeriesId(id)}
          />
        </div>
        <div className="field">
          <label htmlFor="v2-review-search">Search</label>
          <input
            id="v2-review-search"
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            placeholder="character tag"
          />
        </div>
        <div className="field">
          <label htmlFor="v2-review-prompt-modified">&nbsp;</label>
          <label className="review-checkbox-field">
            <input
              id="v2-review-prompt-modified"
              type="checkbox"
              checked={promptModifiedOnly}
              onChange={(event) => setPromptModifiedOnly(event.target.checked)}
            />
            프롬프트 수정됨만
          </label>
        </div>
        <div className="field" style={{ justifyContent: "flex-end" }}>
          <label>&nbsp;</label>
          <button className="btn" type="button" onClick={() => void loadReviews()}>
            Refresh
          </button>
        </div>
        <ReviewShortcutGuide includeMerge includeMulticolor />
      </div>

      <V2RatingGuide />

      {stats ? (
        <div className="catalog-review-progress">
          전체 {stats.total.toLocaleString()} · pending {stats.pending.toLocaleString()} · in_progress{" "}
          {stats.in_progress.toLocaleString()} · completed {stats.completed.toLocaleString()}
        </div>
      ) : null}

      <div className="catalog-review-progress">
        {items.length.toLocaleString()} / {total.toLocaleString()} 표시 · 페이지 {currentPage}/{pageCount}
        {focusedItem ? ` · focus: ${focusedItem.character_tag}` : ""}
      </div>

      {error ? <div className="error-banner">{error}</div> : null}
      {actionMessage ? <div className="catalog-card-subtitle" style={{ marginBottom: 8 }}>{actionMessage}</div> : null}

      {loading ? (
        <div className="empty-state">Loading V2 reviews...</div>
      ) : items.length === 0 ? (
        <div className="empty-state panel">검수할 캐릭터가 없습니다.</div>
      ) : (
        <div ref={scrollRef} className="v2-review-grid" style={gridStyle}>
          {items.map((item, rowIndex) => {
            const draft = drafts[item.id] ?? createV2DraftForItem(item);
            const focused = rowIndex === focusIndex;
            const locked = submittingId === item.id || isCharacterRegenerating(item.id);
            const regenerateJob = v2Jobs[item.id];
            return (
              <V2ReviewRow
                key={item.id}
                item={item}
                rowIndex={rowIndex}
                focused={focused}
                draft={draft}
                thumbSize={thumbSize}
                locked={locked}
                regenerateMessage={regenerateJob?.message}
                regenerateProgress={
                  regenerateJob && regenerateJob.total > 0
                    ? { current: regenerateJob.current, total: regenerateJob.total }
                    : null
                }
                onSelect={() => setFocusIndex(rowIndex)}
                onDraftChange={(next) => updateDraft(item.id, next)}
                onToggleTag={(tagKey) => toggleTag(item.id, tagKey)}
                onRate={(value) => setRating(item.id, value)}
                onRegenerate={focused ? () => void regenerateFocused() : undefined}
                onComplete={() => void completeItem(item)}
                onOpenLinkModal={() => setLinkingItem(item)}
                regenerating={locked}
              />
            );
          })}
        </div>
      )}

      {previewOpen && previewSrc ? (
        <ReviewImagePreview
          src={previewSrc}
          alt={previewAlt}
          original
          fitToScreen={previewFit}
          onToggleFit={() => setPreviewFit((fit) => !fit)}
          onClose={() => setPreviewOpen(false)}
        />
      ) : null}

      {popupOpen && focusedItem ? (
        <div
          className="v2-multicolor-popup"
          style={{ top: popupPosition?.top ?? 8, left: popupPosition?.left ?? 8 }}
          role="listbox"
          aria-label="multicolor 옵션"
        >
          <div className="v2-multicolor-popup-title">Multicolor 옵션 (↑↓ 이동 · Enter 토글 · Esc 닫기)</div>
          {multicolorChips.map((chip, index) => {
            const enabled =
              (drafts[focusedItem.id]?.enabledTags.size ?? 0) > 0
                ? drafts[focusedItem.id]!.enabledTags.has(chip.key)
                : defaultEnabledTagKeys(v2AppearanceTagChips(focusedItem)).has(chip.key);
            return (
              <button
                key={chip.key}
                type="button"
                role="option"
                aria-selected={index === popupIndex}
                className={`v2-multicolor-popup-option${index === popupIndex ? " v2-multicolor-popup-option--active" : ""}${
                  enabled ? " v2-multicolor-popup-option--enabled" : ""
                }`}
                onClick={() => {
                  setPopupIndex(index);
                  toggleTag(focusedItem.id, chip.key);
                }}
              >
                {chip.suggested ? "추천: " : ""}
                {chip.label}
                {enabled ? " ✓" : ""}
              </button>
            );
          })}
        </div>
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
