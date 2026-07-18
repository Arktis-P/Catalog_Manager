import { useState } from "react";
import type { V2ReviewCharacter, V2ReviewImage } from "../../types";
import { danbooruPostsUrl, danbooruWikiUrl } from "../../utils/danbooruLinks";
import {
  appearanceTagChips,
  buildFinalPrompt,
  cycleGender,
  defaultEnabledTagKeys,
  genderChipClass,
  genderChipLabel,
  MULTI_HAIR_OPTIONS,
  stripHairSuffix,
} from "../../utils/reviewPrompt";
import { LazyReviewImage } from "./LazyReviewImage";
import { ReviewRatingStars } from "./ReviewRatingStars";

export interface V2CharacterDraft {
  imageIndex: number;
  gender: string | null;
  rating: number | null;
  enabledTags: Set<string>;
  customPrompt: string | null;
  promptEdited: boolean;
}

export type V2AppearanceChip = ReturnType<typeof appearanceTagChips>[number] & { suggested?: boolean };

function suggestedMulticolorTags(character: V2ReviewCharacter): string[] {
  const tags = new Set<string>();
  for (const image of character.images) {
    for (const tag of (image.suggested_multicolor_tags ?? "").split(",")) {
      const trimmed = tag.trim();
      if (trimmed) {
        tags.add(trimmed);
      }
    }
  }
  return Array.from(tags);
}

// GlobalCharacter의 외형 태그 후보(appearanceTagChips)에 자동 재현 검사가 추천한
// multicolor 태그(V2 전용)를 합쳐, V2 카드에서 클릭 한 번으로 추가할 수 있게 한다.
export function v2AppearanceTagChips(character: V2ReviewCharacter): V2AppearanceChip[] {
  const chips: V2AppearanceChip[] = appearanceTagChips(character);
  const existingKeys = new Set(chips.map((chip) => chip.key));
  for (const tag of suggestedMulticolorTags(character)) {
    const key = `multi:${tag}`;
    if (existingKeys.has(key)) {
      continue;
    }
    existingKeys.add(key);
    chips.push({ key, label: tag.replace(/_/g, " "), group: "multi", optional: true, suggested: true });
  }
  return chips;
}

function enabledTagsFromSelectedTags(selectedTags: string | null, chips: V2AppearanceChip[]): Set<string> | null {
  if (!selectedTags) {
    return null;
  }
  const raw = new Set(
    selectedTags
      .split(",")
      .map((tag) => tag.trim())
      .filter(Boolean),
  );
  const enabled = new Set<string>();
  for (const chip of chips) {
    if (chip.group === "gender") {
      continue;
    }
    const value = chip.key.slice(chip.key.indexOf(":") + 1);
    if (raw.has(value)) {
      enabled.add(chip.key);
    }
  }
  return enabled.size > 0 ? enabled : null;
}

function enabledTagsFromPrompt(basePrompt: string | null, chips: V2AppearanceChip[]): Set<string> | null {
  if (!basePrompt) {
    return null;
  }
  const enabled = new Set<string>();
  for (const chip of chips) {
    if (chip.group === "gender") {
      continue;
    }
    if (basePrompt.includes(chip.label)) {
      enabled.add(chip.key);
    }
  }
  return enabled.size > 0 ? enabled : null;
}

export function createV2DraftForItem(character: V2ReviewCharacter): V2CharacterDraft {
  const chips = v2AppearanceTagChips(character);
  // 서버가 저장한 selected_tags(리뷰 재방문) > base_prompt 텍스트 파싱(최초 리뷰, 서버가 관련도
  // 기준으로 이미 구성해 둔 프롬프트) > 기본값(첫 머리색만 활성화) 순으로 활성 태그를 복원한다.
  const enabledTags =
    enabledTagsFromSelectedTags(character.selected_tags, chips) ??
    enabledTagsFromPrompt(character.base_prompt, chips) ??
    defaultEnabledTagKeys(chips);
  const autoPrompt = buildFinalPrompt(character.character_tag, character.base_prompt, enabledTags, chips);
  const promptEdited = Boolean(character.base_prompt && character.base_prompt !== autoPrompt);
  const coverIndex = character.images.findIndex(
    (image) => image.is_cover || image.id === character.cover_image_id,
  );

  return {
    imageIndex: coverIndex >= 0 ? coverIndex : 0,
    gender: character.gender,
    rating: character.rating,
    enabledTags,
    customPrompt: promptEdited ? character.base_prompt : null,
    promptEdited,
  };
}

export function resolveV2FinalPrompt(character: V2ReviewCharacter, draft: V2CharacterDraft): string {
  if (draft.promptEdited && draft.customPrompt !== null) {
    return draft.customPrompt;
  }
  const chips = v2AppearanceTagChips(character);
  const enabledTags = draft.enabledTags.size > 0 ? draft.enabledTags : defaultEnabledTagKeys(chips);
  return buildFinalPrompt(character.character_tag, character.base_prompt, enabledTags, chips) ?? "";
}

export function v2SelectedTagsPayload(character: V2ReviewCharacter, enabledTagKeys: Set<string>): string | null {
  const chips = v2AppearanceTagChips(character);
  const enabled = enabledTagKeys.size > 0 ? enabledTagKeys : defaultEnabledTagKeys(chips);
  const rawTags = chips
    .filter((chip) => chip.group !== "gender" && enabled.has(chip.key))
    .map((chip) => chip.key.slice(chip.key.indexOf(":") + 1));
  return rawTags.length > 0 ? rawTags.join(",") : null;
}

function statusDotClass(status: string | null | undefined): string {
  if (status === "warning") return "v2-status-dot v2-status-dot--warning";
  if (status === "reject") return "v2-status-dot v2-status-dot--reject";
  return "v2-status-dot v2-status-dot--pass";
}

function qualityDotTitle(image: V2ReviewImage): string {
  const label =
    image.quality_status === "warning"
      ? "품질 확인 필요"
      : image.quality_status === "reject"
        ? "품질 실패"
        : "품질 확인됨";
  return image.quality_reasons ? `${label}: ${image.quality_reasons}` : label;
}

function identityDotTitle(image: V2ReviewImage): string {
  const label =
    image.identity_status === "warning"
      ? "캐릭터 재현 확인 필요"
      : image.identity_status === "reject"
        ? "캐릭터 재현 실패"
        : "캐릭터 재현 확인됨";
  return image.identity_reasons ? `${label}: ${image.identity_reasons}` : label;
}

function generationStatusBadge(status: string): { label: string; className: string } | null {
  if (status === "generation_failed") {
    return { label: "생성 실패", className: "badge badge-danger" };
  }
  if (status === "likely_untrained") {
    return { label: "학습 안 된 캐릭터 가능", className: "badge badge-danger" };
  }
  return null;
}

function humanizeTag(tag: string): string {
  return tag.replace(/_/g, " ");
}

interface V2ReviewRowProps {
  item: V2ReviewCharacter;
  rowIndex: number;
  focused: boolean;
  draft: V2CharacterDraft;
  thumbSize: number;
  locked?: boolean;
  regenerateMessage?: string;
  regenerateProgress?: { current: number; total: number } | null;
  onSelect?: () => void;
  onDraftChange: (draft: V2CharacterDraft) => void;
  onToggleTag: (tagKey: string) => void;
  onRate: (value: number) => void;
  onRegenerate?: () => void;
  onComplete?: () => void;
  onOpenLinkModal?: () => void;
  regenerating?: boolean;
}

export function V2ReviewRow({
  item,
  rowIndex,
  focused,
  draft,
  thumbSize,
  locked = false,
  regenerateMessage,
  regenerateProgress,
  onSelect,
  onDraftChange,
  onToggleTag,
  onRate,
  onRegenerate,
  onComplete,
  onOpenLinkModal,
  regenerating = false,
}: V2ReviewRowProps) {
  const [showParentInfo, setShowParentInfo] = useState(false);
  const chips = v2AppearanceTagChips(item);
  const enabledTags = draft.enabledTags.size > 0 ? draft.enabledTags : defaultEnabledTagKeys(chips);
  const promptText = resolveV2FinalPrompt(item, draft);
  const displayGender = draft.gender ?? item.gender;
  const hairRowChips = chips.filter(
    (chip) =>
      (chip.group === "hair" || chip.group === "multi" || chip.group === "shape") && !chip.optional && !chip.suggested,
  );
  const suggestedChips = chips.filter((chip) => chip.suggested);
  const optionalMultiChips = MULTI_HAIR_OPTIONS.filter(
    (option) => !suggestedChips.some((chip) => chip.key === option.key),
  );
  const featureRowChips = chips.filter((chip) => chip.group === "eyes" || chip.group === "features");
  const genStatusBadge = generationStatusBadge(item.generation_status);
  const currentImage = item.images[draft.imageIndex] ?? null;
  const hasMultipleImages = item.images.length > 1;
  const displayName = humanizeTag(item.display_name || item.character_tag);
  const primarySeriesTag = item.series_tags[0] ?? null;

  const shiftImage = (delta: -1 | 1) => {
    if (locked) return;
    const maxIndex = Math.max(0, item.images.length - 1);
    const nextIndex = Math.min(maxIndex, Math.max(0, draft.imageIndex + delta));
    if (nextIndex !== draft.imageIndex) {
      onDraftChange({ ...draft, imageIndex: nextIndex });
    }
  };

  return (
    <article
      className={`v2-review-card${focused ? " v2-review-card--focused" : ""}${locked ? " v2-review-card--locked" : ""}`}
      data-row-index={rowIndex}
      data-character-id={item.id}
      onMouseDown={onSelect}
    >
      {locked && regenerateMessage ? (
        <div className="v2-review-card-regenerate-banner">
          <span>{regenerateMessage}</span>
          {regenerateProgress && regenerateProgress.total > 0 ? (
            <span className="catalog-review-regenerate-progress">
              {regenerateProgress.current}/{regenerateProgress.total}
            </span>
          ) : null}
        </div>
      ) : null}

      <div className="v2-review-card-image-wrap">
        {currentImage ? (
          <>
            <LazyReviewImage
              imagePath={currentImage.image_path}
              alt={`${item.character_tag} ${draft.imageIndex + 1}`}
              active={focused}
              thumbSize={thumbSize}
            />
            <div className="v2-review-card-overlay">
              <span className={statusDotClass(currentImage.quality_status)} title={qualityDotTitle(currentImage)} />
              <span className={statusDotClass(currentImage.identity_status)} title={identityDotTitle(currentImage)} />
              {currentImage.is_provisional ? <span className="badge badge-warning">임시 대표</span> : null}
              {item.images.length > 1 ? (
                <span className="v2-review-card-image-count">
                  {draft.imageIndex + 1}/{item.images.length}
                </span>
              ) : null}
            </div>
            {hasMultipleImages ? (
              <>
                <button
                  type="button"
                  className="v2-review-card-nav-btn v2-review-card-nav-btn--prev"
                  disabled={locked || draft.imageIndex === 0}
                  onClick={() => shiftImage(-1)}
                  aria-label="이전 이미지"
                >
                  ‹
                </button>
                <button
                  type="button"
                  className="v2-review-card-nav-btn v2-review-card-nav-btn--next"
                  disabled={locked || draft.imageIndex >= item.images.length - 1}
                  onClick={() => shiftImage(1)}
                  aria-label="다음 이미지"
                >
                  ›
                </button>
              </>
            ) : null}
          </>
        ) : (
          <div className="review-image-slot review-image-slot--empty">
            <span className="review-image-placeholder">No image</span>
          </div>
        )}
      </div>

      <div className="v2-review-card-body">
        <div className="v2-review-card-name-row">
          <h3 className="v2-review-card-name">{displayName}</h3>
          {item.is_alternative ? (
            <button
              type="button"
              className="badge badge-alternative v2-review-card-altered-tag"
              onClick={() => setShowParentInfo((current) => !current)}
              title="상위 캐릭터 정보 보기"
            >
              altered
            </button>
          ) : null}
        </div>
        {showParentInfo && item.is_alternative ? (
          <div className="catalog-card-subtitle">
            상위: {humanizeTag(item.parent_display_name || item.parent_character_tag || "미상")}
            {item.parent_character_tag ? ` (${item.parent_character_tag})` : ""}
          </div>
        ) : null}

        <div className="v2-review-card-series-row">
          <span className="catalog-card-subtitle">{primarySeriesTag ? humanizeTag(primarySeriesTag) : "-"}</span>
          <span className="badge">{item.post_count.toLocaleString()} posts</span>
        </div>

        <div className="catalog-review-meta">
          {genStatusBadge ? <span className={genStatusBadge.className}>{genStatusBadge.label}</span> : null}
          {item.prompt_modified ? <span className="badge badge-warning">프롬프트 보정됨</span> : null}
          {item.primary_hair_needs_review ? <span className="badge badge-warning">대표 머리색 확인 필요</span> : null}
          <span className="badge badge-muted">시도 {item.generation_attempts}회</span>
        </div>

        <ReviewRatingStars rating={draft.rating} onRate={locked ? () => undefined : onRate} />

        <div className="catalog-review-tags-stack">
          <div className="catalog-review-tags catalog-review-tags--hair">
            <button
              type="button"
              className={genderChipClass(displayGender)}
              disabled={locked}
              onClick={() => onDraftChange({ ...draft, gender: cycleGender(displayGender) })}
            >
              {genderChipLabel(displayGender)}
            </button>
            {hairRowChips.map((chip) => (
              <button
                key={chip.key}
                type="button"
                className={`review-tag${enabledTags.has(chip.key) ? " review-tag--enabled" : ""}`}
                onClick={() => onToggleTag(chip.key)}
                disabled={locked}
              >
                {chip.group === "multi" ? stripHairSuffix(chip.label) : chip.label}
              </button>
            ))}
          </div>
          <div className="catalog-review-tags catalog-review-tags--multi-options">
            {optionalMultiChips.map((option) => (
              <button
                key={option.key}
                type="button"
                className={`review-tag${enabledTags.has(option.key) ? " review-tag--enabled" : ""}`}
                onClick={() => onToggleTag(option.key)}
                disabled={locked}
              >
                {option.label}
              </button>
            ))}
          </div>
          {suggestedChips.length > 0 ? (
            <div className="catalog-review-tags catalog-review-tags--suggested">
              {suggestedChips.map((chip) => (
                <button
                  key={chip.key}
                  type="button"
                  className={`review-tag review-tag--suggested${enabledTags.has(chip.key) ? " review-tag--enabled" : ""}`}
                  onClick={() => onToggleTag(chip.key)}
                  disabled={locked}
                  title="자동 재현 검사 추천 multicolor 태그"
                >
                  추천: {stripHairSuffix(chip.label)}
                </button>
              ))}
            </div>
          ) : null}
          {featureRowChips.length > 0 ? (
            <div className="catalog-review-tags catalog-review-tags--features">
              {featureRowChips.map((chip) => (
                <button
                  key={chip.key}
                  type="button"
                  className={`review-tag${enabledTags.has(chip.key) ? " review-tag--enabled" : ""}`}
                  onClick={() => onToggleTag(chip.key)}
                  disabled={locked}
                >
                  {chip.label}
                </button>
              ))}
            </div>
          ) : null}
        </div>

        <div className="catalog-review-prompt-field">
          <div className="catalog-review-prompt-header">
            <label htmlFor={`v2-review-prompt-${item.id}`}>Base Prompt</label>
            {draft.promptEdited ? (
              <button
                type="button"
                className="btn btn-small btn-ghost"
                onClick={() =>
                  onDraftChange({
                    ...draft,
                    customPrompt: null,
                    promptEdited: false,
                  })
                }
              >
                Reset tags
              </button>
            ) : null}
          </div>
          <textarea
            id={`v2-review-prompt-${item.id}`}
            className="catalog-review-prompt-input"
            value={promptText}
            rows={2}
            spellCheck={false}
            readOnly={locked}
            onChange={(event) =>
              onDraftChange({
                ...draft,
                customPrompt: event.target.value,
                promptEdited: true,
              })
            }
            placeholder="e.g. 1.2::hakurei reimu::, brown hair"
          />
        </div>

        <div className="v2-review-card-actions">
          <a
            className="btn btn-small"
            href={danbooruPostsUrl(item.character_tag, item.series_tags[0] ?? "")}
            target="_blank"
            rel="noreferrer"
          >
            Posts
          </a>
          <a
            className="btn btn-small"
            href={danbooruWikiUrl(item.character_tag, item.danbooru_wiki_url)}
            target="_blank"
            rel="noreferrer"
          >
            Wiki
          </a>
          {onOpenLinkModal ? (
            <button className="btn btn-small" type="button" onClick={onOpenLinkModal}>
              Merge
            </button>
          ) : null}
          {onRegenerate ? (
            <button
              className="btn btn-small"
              type="button"
              disabled={regenerating || !promptText.trim()}
              onClick={onRegenerate}
            >
              {regenerating ? "재생성 중..." : "Regenerate"}
            </button>
          ) : null}
          {onComplete ? (
            <button
              className="btn btn-primary btn-small v2-review-card-complete"
              type="button"
              disabled={locked}
              onClick={onComplete}
            >
              Complete
            </button>
          ) : null}
        </div>
      </div>
    </article>
  );
}
