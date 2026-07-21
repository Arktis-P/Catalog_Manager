import { useCallback, useEffect, useMemo, useRef, useState, type CSSProperties } from "react";
import { api } from "../../api/client";
import { useGenerationJobs } from "../../context/GenerationJobContext";
import { CharacterLinkModal } from "../CharacterLinkModal";
import { SeriesSearchSelect } from "../SeriesSearchSelect";
import type {
  LinkableCharacterSummary,
  Series,
  V2GenerationJobState,
  V2ReviewCharacter,
  V2ReviewStats,
  V2ReviewStatus,
} from "../../types";
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
  type V2ReviewCardSaveStatus,
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

function sameStringSet(left: Set<string>, right: Set<string>): boolean {
  return left.size === right.size && Array.from(left).every((value) => right.has(value));
}

function isDraftChanged(item: V2ReviewCharacter, draft: V2CharacterDraft): boolean {
  const initial = createV2DraftForItem(item);
  return (
    draft.imageIndex !== initial.imageIndex ||
    draft.gender !== initial.gender ||
    draft.rating !== initial.rating ||
    draft.customPrompt !== initial.customPrompt ||
    draft.promptEdited !== initial.promptEdited ||
    !sameStringSet(draft.enabledTags, initial.enabledTags)
  );
}

export function V2ReviewPanel() {
  const scrollRef = useRef<HTMLDivElement>(null);
  const focusCardFromKeyboardRef = useRef(false);
  const [items, setItems] = useState<V2ReviewCharacter[]>([]);
  const [total, setTotal] = useState(0);
  const [stats, setStats] = useState<V2ReviewStats | null>(null);

  const [reviewStatus, setReviewStatus] = useState<V2ReviewStatus>("pending");
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
  const [dirtyIds, setDirtyIds] = useState<Set<number>>(() => new Set());
  const [savingIds, setSavingIds] = useState<Set<number>>(() => new Set());
  const [failedMessages, setFailedMessages] = useState<Record<number, string>>({});
  const [submittingId, setSubmittingId] = useState<number | null>(null);
  const [bulkSaving, setBulkSaving] = useState(false);
  const [thumbSize, setThumbSize] = useState(384);
  const [cardSize, setCardSize] = useState<V2ReviewCardSize>("medium");
  const [cardWidthPx, setCardWidthPx] = useState(0);
  const [gridCols, setGridCols] = useState(1);
  const [previewOpen, setPreviewOpen] = useState(false);
  const [previewFit, setPreviewFit] = useState(true);
  const [linkingItem, setLinkingItem] = useState<V2ReviewCharacter | null>(null);
  const [pageInput, setPageInput] = useState("1");

  const { v2Jobs: contextV2Jobs, startV2Regeneration } = useGenerationJobs();
  const processedV2JobIdsRef = useRef<Set<string>>(new Set());
  const v2JobsByCharacter = useMemo(() => {
    const next: Record<number, V2GenerationJobState> = {};
    for (const job of contextV2Jobs) {
      if (job.kind === "regenerate" && job.character_id != null) {
        next[job.character_id] = job;
      }
    }
    return next;
  }, [contextV2Jobs]);

  const itemsRef = useRef<V2ReviewCharacter[]>([]);
  useEffect(() => {
    itemsRef.current = items;
  }, [items]);

  const isCharacterRegenerating = useCallback(
    (characterId: number) => {
      const job = v2JobsByCharacter[characterId];
      return Boolean(job && (job.status === "queued" || job.status === "running" || job.status === "paused"));
    },
    [v2JobsByCharacter],
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
    // items.length: 그리드는 목록 로드 후에 렌더되므로, 첫 로드 시점에 ref가 채워진 뒤 다시 측정해야 한다.
  }, [effectiveCardWidthPx, items.length]);

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

  const addToSet = (values: Set<number>, id: number) => {
    const next = new Set(values);
    next.add(id);
    return next;
  };

  const removeFromSet = (values: Set<number>, id: number) => {
    const next = new Set(values);
    next.delete(id);
    return next;
  };

  const removeManyFromSet = (values: Set<number>, ids: Set<number>) => {
    const next = new Set(values);
    for (const id of ids) {
      next.delete(id);
    }
    return next;
  };

  const clearFailedMessage = (characterId: number) => {
    setFailedMessages((current) => {
      if (!(characterId in current)) {
        return current;
      }
      const next = { ...current };
      delete next[characterId];
      return next;
    });
  };

  const forgetDraft = (characterId: number) => {
    setDrafts((current) => {
      if (!(characterId in current)) {
        return current;
      }
      const next = { ...current };
      delete next[characterId];
      return next;
    });
  };

  const updateDraft = (characterId: number, draft: V2CharacterDraft) => {
    setDrafts((current) => ({ ...current, [characterId]: draft }));
    const item = itemsRef.current.find((entry) => entry.id === characterId);
    setDirtyIds((current) =>
      item && !isDraftChanged(item, draft) ? removeFromSet(current, characterId) : addToSet(current, characterId),
    );
    clearFailedMessage(characterId);
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
    if (value === 4) {
      setActionMessage("레이팅 4는 V2 1차 검수에서 비권장입니다. 다시 4를 눌러 해제하거나 1/2/3/5/6으로 수정할 수 있습니다.");
    }
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
    const completedIndex = itemsRef.current.findIndex((entry) => entry.id === item.id);

    setSubmittingId(item.id);
    setSavingIds((current) => addToSet(current, item.id));
    clearFailedMessage(item.id);
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
      setDirtyIds((current) => removeFromSet(current, item.id));
      clearFailedMessage(item.id);
      forgetDraft(item.id);
      const nextItems = itemsRef.current.filter((entry) => entry.id !== item.id);
      setItems(nextItems);
      setTotal((current) => Math.max(0, current - 1));
      focusCardFromKeyboardRef.current = true;
      setFocusIndex(Math.min(completedIndex >= 0 ? completedIndex : focusIndex, Math.max(0, nextItems.length - 1)));
      await loadReviews();
      await loadStats();
    } catch (err) {
      const message = err instanceof Error ? err.message : "리뷰 완료에 실패했습니다.";
      setError(message);
      setFailedMessages((current) => ({ ...current, [item.id]: message }));
      setDirtyIds((current) => addToSet(current, item.id));
    } finally {
      setSubmittingId(null);
      setSavingIds((current) => removeFromSet(current, item.id));
    }
  };

  const bulkSaveRatedItems = useCallback(async () => {
    if (bulkSaving) {
      return;
    }
    const eligible = items.filter((item) => {
      if (isCharacterRegenerating(item.id)) return false;
      const draft = drafts[item.id];
      const rating = draft ? draft.rating : item.rating;
      return rating !== null && rating !== undefined;
    });
    if (eligible.length === 0) {
      setActionMessage("일괄 저장할 레이팅된 항목이 없습니다.");
      return;
    }

    setBulkSaving(true);
    const eligibleIds = new Set(eligible.map((item) => item.id));
    setSavingIds((current) => {
      const next = new Set(current);
      for (const id of eligibleIds) {
        next.add(id);
      }
      return next;
    });
    setFailedMessages((current) => {
      const next = { ...current };
      for (const id of eligibleIds) {
        delete next[id];
      }
      return next;
    });
    setError(null);
    try {
      const payloadItems = eligible.map((item) => {
        const draft = drafts[item.id] ?? createV2DraftForItem(item);
        const rating = draft.rating;
        const chips = v2AppearanceTagChips(item);
        const enabledTags = draft.enabledTags.size > 0 ? draft.enabledTags : defaultEnabledTagKeys(chips);
        const finalPrompt = resolveV2FinalPrompt(item, { ...draft, enabledTags });
        const defaultCoverIndex = item.images.findIndex(
          (image) => image.is_cover || image.id === item.cover_image_id,
        );
        const defaultImageIndex = defaultCoverIndex >= 0 ? defaultCoverIndex : 0;
        const selectedImage = item.images[draft.imageIndex];
        const coverImageId =
          draft.imageIndex !== defaultImageIndex && selectedImage ? selectedImage.id : undefined;
        return {
          character_id: item.id,
          rating,
          gender: draft.gender,
          base_prompt: finalPrompt,
          selected_tags: v2SelectedTagsPayload(item, enabledTags),
          cover_image_id: coverImageId,
        };
      });
      const response = await api.bulkCompleteV2ReviewCharacters({ items: payloadItems });
      const failedTags = response.results
        .filter((result) => result.status === "failed")
        .map((result) => {
          const failedItem = items.find((entry) => entry.id === result.character_id);
          return failedItem ? failedItem.character_tag : `#${result.character_id}`;
        });
      const failedResults = response.results.filter((result) => result.status === "failed");
      const failedIds = new Set(failedResults.map((result) => result.character_id));
      const succeededIds = new Set(
        response.results.filter((result) => result.status === "completed").map((result) => result.character_id),
      );
      setActionMessage(`완료 ${response.completed} · 건너뜀 ${response.skipped} · 실패 ${response.failed}`);
      if (failedTags.length > 0) {
        setError(`일괄 저장 실패: ${failedTags.join(", ")}`);
        setFailedMessages((current) => {
          const next = { ...current };
          for (const result of failedResults) {
            const failedItem = items.find((entry) => entry.id === result.character_id);
            next[result.character_id] = result.error || `${failedItem?.character_tag ?? result.character_id} 저장 실패`;
          }
          return next;
        });
        const firstFailedIndex = items.findIndex((entry) => failedIds.has(entry.id));
        if (firstFailedIndex >= 0) {
          focusCardFromKeyboardRef.current = true;
          setFocusIndex(firstFailedIndex);
        }
      }
      setDirtyIds((current) => removeManyFromSet(current, succeededIds));
      for (const id of succeededIds) {
        clearFailedMessage(id);
        forgetDraft(id);
      }
      if (failedTags.length === 0) {
        setFocusIndex(0);
        scrollRef.current?.scrollTo({ top: 0 });
      }
      if (skip !== 0) {
        setSkip(0);
      } else {
        await loadReviews();
      }
      await loadStats();
    } catch (err) {
      const message = err instanceof Error ? err.message : "일괄 저장에 실패했습니다.";
      setError(message);
      setFailedMessages((current) => {
        const next = { ...current };
        for (const item of eligible) {
          next[item.id] = message;
        }
        return next;
      });
    } finally {
      setBulkSaving(false);
      setSavingIds((current) => removeManyFromSet(current, eligibleIds));
    }
  }, [bulkSaving, items, drafts, isCharacterRegenerating, skip, loadReviews, loadStats]);

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

  useEffect(() => {
    for (const job of contextV2Jobs) {
      if (
        job.kind === "regenerate" &&
        (job.status === "completed" || job.status === "failed" || job.status === "cancelled")
      ) {
        void onV2JobSettled(job);
      }
    }
  }, [contextV2Jobs, onV2JobSettled]);

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
      if (previewSrc) {
        setPreviewFit(true);
        return true;
      }
      return false;
    });
  }, [focusedLocked, previewSrc]);

  const cycleFocusedMulticolor = useCallback(() => {
    if (!focusedItem || !focusedDraft || focusedLocked || multicolorChips.length === 0) {
      return;
    }
    const allChips = v2AppearanceTagChips(focusedItem);
    const enabled = new Set(
      focusedDraft.enabledTags.size > 0 ? focusedDraft.enabledTags : defaultEnabledTagKeys(allChips),
    );
    const enabledMultiIndexes = multicolorChips
      .map((chip, index) => (enabled.has(chip.key) ? index : -1))
      .filter((index) => index >= 0);
    const nextIndex = enabledMultiIndexes.length === 1 ? (enabledMultiIndexes[0] + 1) % multicolorChips.length : 0;
    for (const chip of multicolorChips) {
      enabled.delete(chip.key);
    }
    enabled.add(multicolorChips[nextIndex].key);
    updateDraft(focusedItem.id, { ...focusedDraft, enabledTags: enabled });
  }, [focusedDraft, focusedItem, focusedLocked, multicolorChips]);

  const selectFocusedImage = useCallback(
    (index: number) => {
      if (!focusedItem || !focusedDraft || focusedLocked) {
        return;
      }
      if (index < 0 || index >= focusedItem.images.length) {
        return;
      }
      updateDraft(focusedItem.id, { ...focusedDraft, imageIndex: index });
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
      await startV2Regeneration(focusedItem.id, { base_prompt: finalPrompt });
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
  }, [focusedDraft, focusedItem, isCharacterRegenerating, startV2Regeneration]);

  useEffect(() => {
    const node = scrollRef.current;
    if (!node || !focusedItem) {
      return;
    }
    const row = node.querySelector(`[data-character-id="${focusedItem.id}"]`);
    row?.scrollIntoView({ block: "nearest" });
    if (row instanceof HTMLElement && focusCardFromKeyboardRef.current && !isEditableTarget(document.activeElement)) {
      focusCardFromKeyboardRef.current = false;
      row.focus({ preventScroll: true });
    }
  }, [focusIndex, focusedItem]);

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (linkingItem || isEditableTarget(event.target) || !focusedItem || !focusedDraft) {
        return;
      }

      if (event.ctrlKey && event.key === "Enter") {
        event.preventDefault();
        void bulkSaveRatedItems();
        return;
      }

      if (focusedLocked) {
        const key = event.key.toLowerCase();
        const allowed =
          event.key === "ArrowUp" ||
          event.key === "ArrowDown" ||
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
        event.stopPropagation();
        togglePreview();
        return;
      }

      if (event.key === "ArrowLeft") {
        event.preventDefault();
        setFocusIndex((index) => {
          const next = Math.max(0, index - 1);
          focusCardFromKeyboardRef.current = next !== index;
          return next;
        });
        return;
      }

      if (event.key === "ArrowRight") {
        event.preventDefault();
        setFocusIndex((index) => {
          const next = Math.min(items.length - 1, index + 1);
          focusCardFromKeyboardRef.current = next !== index;
          return next;
        });
        return;
      }

      if (event.key === "ArrowUp") {
        event.preventDefault();
        setFocusIndex((index) => {
          const next = Math.max(0, index - gridCols);
          focusCardFromKeyboardRef.current = next !== index;
          return next;
        });
        return;
      }

      if (event.key === "ArrowDown") {
        event.preventDefault();
        setFocusIndex((index) => {
          const next = Math.min(items.length - 1, index + gridCols);
          focusCardFromKeyboardRef.current = next !== index;
          return next;
        });
        return;
      }

      if (event.ctrlKey && event.key >= "1" && event.key <= "9") {
        event.preventDefault();
        selectFocusedImage(Number(event.key) - 1);
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
        cycleFocusedMulticolor();
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
    bulkSaveRatedItems,
    cycleFocusedMulticolor,
    focusedDraft,
    focusedItem,
    focusedLocked,
    gridCols,
    items.length,
    linkingItem,
    regenerateFocused,
    selectFocusedImage,
    togglePreview,
  ]);

  const pageCount = Math.max(1, Math.ceil(total / PAGE_SIZE));
  const currentPage = Math.floor(skip / PAGE_SIZE) + 1;

  useEffect(() => {
    setPageInput(String(currentPage));
  }, [currentPage]);

  const goToPage = useCallback(
    (value: string) => {
      const parsed = Number.parseInt(value, 10);
      const page = Number.isFinite(parsed) ? Math.min(pageCount, Math.max(1, parsed)) : currentPage;
      setPageInput(String(page));
      setSkip((page - 1) * PAGE_SIZE);
    },
    [currentPage, pageCount],
  );

  const renderPaginationControls = () => (
    <div className="series-pagination-controls" aria-label="V2 review pagination">
      <button className="btn btn-small" type="button" disabled={skip === 0} onClick={() => setSkip(0)}>&laquo;</button>
      <button
        className="btn btn-small"
        type="button"
        disabled={skip === 0}
        onClick={() => setSkip((s) => Math.max(0, s - PAGE_SIZE))}
      >
        &lsaquo;
      </button>
      <input
        className="series-pagination-page-input"
        type="number"
        min="1"
        max={pageCount}
        value={pageInput}
        aria-label="V2 review page number"
        onChange={(event) => setPageInput(event.target.value)}
        onBlur={(event) => goToPage(event.target.value)}
        onKeyDown={(event) => {
          if (event.key === "Enter") {
            event.currentTarget.blur();
          }
        }}
      />
      <span className="series-pagination-page-total">/ {pageCount}</span>
      <button
        className="btn btn-small"
        type="button"
        disabled={currentPage >= pageCount}
        onClick={() => setSkip((s) => Math.min((pageCount - 1) * PAGE_SIZE, s + PAGE_SIZE))}
      >
        &rsaquo;
      </button>
      <button
        className="btn btn-small"
        type="button"
        disabled={currentPage >= pageCount}
        onClick={() => setSkip((pageCount - 1) * PAGE_SIZE)}
      >
        &raquo;
      </button>
    </div>
  );

  const gridStyle = { "--v2-card-width": `${effectiveCardWidthPx}px` } as CSSProperties;
  const visibleDirtyCount = items.filter((item) => dirtyIds.has(item.id)).length;
  const visibleFailedCount = items.filter((item) => item.id in failedMessages).length;
  const visibleSavingCount = items.filter((item) => savingIds.has(item.id)).length;
  const remainingLabel = reviewStatus === "pending" && stats ? `${stats.pending.toLocaleString()}개 대기` : `${total.toLocaleString()}개 결과`;
  const activeFilters = [
    `상태 ${reviewStatus === "pending" ? "대기" : reviewStatus === "completed_recent" ? "최근 완료" : reviewStatus}`,
    ratingFilter ? `레이팅 ${ratingFilter}` : null,
    qualityStatus ? `품질 ${qualityStatus}` : null,
    identityStatus ? `재현 ${identityStatus}` : null,
    generationStatus ? `생성 ${generationStatus}` : null,
    genderFilter ? `성별 ${genderFilter}` : null,
    seriesId ? `시리즈 #${seriesId}` : null,
    multicolorFilter ? `multicolor ${multicolorFilter}` : null,
    promptModifiedOnly ? "프롬프트 수정됨" : null,
    search ? `검색 ${search}` : null,
  ].filter(Boolean);
  const statsSummary = stats
    ? `전체 ${stats.total.toLocaleString()} · 대기 ${stats.pending.toLocaleString()} · 진행 ${stats.in_progress.toLocaleString()} · 완료 ${stats.completed.toLocaleString()}`
    : "통계 로딩 중";
  const workSummary = `남은 항목: ${remainingLabel} · 현재 페이지 ${currentPage}/${pageCount} · 표시 ${items.length.toLocaleString()}개 · 미저장 ${visibleDirtyCount} · 저장 중 ${visibleSavingCount} · 실패 ${visibleFailedCount}`;

  const getSaveStatus = (item: V2ReviewCharacter, regenerateJob?: V2GenerationJobState): V2ReviewCardSaveStatus => {
    if (regenerateJob && (regenerateJob.status === "queued" || regenerateJob.status === "running" || regenerateJob.status === "paused")) {
      const detail =
        regenerateJob.total > 0 ? `${regenerateJob.current}/${regenerateJob.total}` : regenerateJob.message || undefined;
      return { kind: "regenerating", label: "재생성 중", detail };
    }
    if (savingIds.has(item.id) || submittingId === item.id) {
      return { kind: "saving", label: "저장 중" };
    }
    if (failedMessages[item.id]) {
      return { kind: "failed", label: "저장 실패", detail: failedMessages[item.id] };
    }
    if (dirtyIds.has(item.id)) {
      return { kind: "dirty", label: "미저장 변경" };
    }
    return item.review_status === "completed"
      ? { kind: "clean", label: "저장됨" }
      : { kind: "clean", label: "변경 없음" };
  };

  return (
    <>
      <div className="toolbar review-toolbar">
        <div className="field">
          <label htmlFor="v2-review-status">리뷰 상태</label>
          <select
            id="v2-review-status"
            value={reviewStatus}
            onChange={(event) => setReviewStatus(event.target.value as V2ReviewStatus)}
          >
            <option value="pending">대기 중</option>
            <option value="completed_recent">완료(최근순)</option>
          </select>
        </div>
        <div className="field">
          <label htmlFor="v2-review-search">검색</label>
          <input
            id="v2-review-search"
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            placeholder="character tag"
          />
        </div>
        <div className="field" style={{ justifyContent: "flex-end" }}>
          <label>&nbsp;</label>
          <button className="btn" type="button" onClick={() => void loadReviews()}>
            새로고침
          </button>
        </div>
        <div className="field" style={{ justifyContent: "flex-end" }}>
          <label>&nbsp;</label>
          <button
            className="btn btn-primary"
            type="button"
            disabled={bulkSaving}
            title="Ctrl+Enter"
            onClick={() => void bulkSaveRatedItems()}
          >
            {bulkSaving ? "저장 중..." : "레이팅된 항목 일괄 저장 (Ctrl+Enter)"}
          </button>
        </div>
        {renderPaginationControls()}
        <div className="catalog-review-progress">
          <div>{statsSummary}</div>
          <div>
            {workSummary}
            {focusedItem ? ` · 현재 ${focusedItem.character_tag}` : ""}
          </div>
          <div>필터: {activeFilters.length > 0 ? activeFilters.join(" · ") : "없음"}</div>
        </div>
      </div>

      <details className="review-rating-guide">
        <summary className="review-rating-guide-summary">
          <span className="review-rating-guide-title">상세 필터</span>
          <span className="review-rating-guide-hint">레이팅 · 품질 · 재현 · 성별 · 시리즈 · multicolor · 프롬프트</span>
        </summary>
        <div className="toolbar review-toolbar">
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
          <ReviewShortcutGuide includeMerge includeMulticolor v2Layout />
        </div>
      </details>

      <V2RatingGuide />

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
            const locked = submittingId === item.id || savingIds.has(item.id) || isCharacterRegenerating(item.id);
            const regenerateJob = v2JobsByCharacter[item.id];
            const saveStatus = getSaveStatus(item, regenerateJob);
            return (
              <V2ReviewRow
                key={item.id}
                item={item}
                rowIndex={rowIndex}
                focused={focused}
                draft={draft}
                thumbSize={thumbSize}
                locked={locked}
                saveStatus={saveStatus}
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

      {linkingItem ? (
        <CharacterLinkModal
          character={toLinkableSummary(linkingItem)}
          onClose={() => setLinkingItem(null)}
          onLinked={() => void loadReviews()}
        />
      ) : null}

      {total > PAGE_SIZE ? (
        <div className="series-pagination">
          {renderPaginationControls()}
        </div>
      ) : null}
    </>
  );
}
