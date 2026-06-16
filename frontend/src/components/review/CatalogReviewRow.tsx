import type { CatalogReviewItem } from "../../types";
import { danbooruPostsUrl, danbooruWikiUrl } from "../../utils/danbooruLinks";
import {
  appearanceTagChips,
  buildFinalPrompt,
  defaultEnabledTagKeys,
  genderChipClass,
} from "../../utils/reviewPrompt";
import { LazyReviewImage } from "./LazyReviewImage";

export interface CharacterDraft {
  imageIndex: number;
  gender: string | null;
  rating: number | null;
  enabledTags: Set<string>;
}

interface CatalogReviewRowProps {
  item: CatalogReviewItem;
  rowIndex: number;
  focused: boolean;
  draft: CharacterDraft;
  onDraftChange: (draft: CharacterDraft) => void;
  onToggleTag: (tagKey: string) => void;
}

function autoStatusClass(status: string | null): string {
  if (status === "pass") return "badge badge-success";
  if (status === "warning") return "badge badge-warning";
  if (status === "reject_candidate") return "badge badge-muted";
  return "badge";
}

export function CatalogReviewRow({
  item,
  rowIndex,
  focused,
  draft,
  onDraftChange,
  onToggleTag,
}: CatalogReviewRowProps) {
  const chips = appearanceTagChips(item);
  const enabledTags = draft.enabledTags.size > 0 ? draft.enabledTags : defaultEnabledTagKeys(chips);
  const finalPrompt = buildFinalPrompt(item.character_tag, item.generation_prompt, enabledTags, chips);
  const displayGender = draft.gender ?? item.gender;
  const imageSlots = item.images.slice(0, 4);
  const paddedSlots = imageSlots.length >= 2 ? imageSlots : [...imageSlots, ...Array(Math.max(0, 2 - imageSlots.length)).fill(null)];

  return (
    <article
      className={`catalog-review-row${focused ? " catalog-review-row--focused" : ""}`}
      data-row-index={rowIndex}
      data-character-id={item.id}
    >
      <div className="catalog-review-images">
        {paddedSlots.slice(0, 2).map((image, index) =>
          image ? (
            <div key={image.id} className="catalog-review-image-cell">
              <LazyReviewImage
                imagePath={image.image_path}
                alt={`${item.character_tag} ${index + 1}`}
                active={focused}
                selected={focused && draft.imageIndex === index}
                onClick={() => onDraftChange({ ...draft, imageIndex: index })}
              />
              <div className="catalog-review-image-meta">
                <span className={autoStatusClass(image.auto_status)}>{image.auto_status || "unknown"}</span>
                {image.cover_score !== null ? <span className="badge">{image.cover_score.toFixed(2)}</span> : null}
              </div>
            </div>
          ) : (
            <div key={`empty-${index}`} className="catalog-review-image-cell">
              <div className="review-image-slot review-image-slot--empty">
                <span className="review-image-placeholder">No image</span>
              </div>
            </div>
          ),
        )}
      </div>

      <aside className="catalog-review-info">
        {item.character_status === "needs_check" && item.needs_check_reason ? (
          <div className="review-needs-check-banner" title={item.needs_check_reason}>
            needs_check: {item.needs_check_reason}
          </div>
        ) : null}

        <div className="catalog-review-info-header">
          <div>
            <h3 className="catalog-review-name">{item.character_tag}</h3>
            <div className="catalog-review-series">{item.series_tag}</div>
          </div>
          <div className="catalog-review-links">
            <a
              className="btn btn-small"
              href={danbooruPostsUrl(item.character_tag, item.series_tag, item.danbooru_url)}
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
          </div>
        </div>

        <div className="catalog-review-meta">
          <span className="badge">{item.post_count.toLocaleString()} posts</span>
          {draft.rating !== null ? <span className="badge">rating {draft.rating}</span> : null}
          {item.review_status ? <span className="badge">{item.review_status}</span> : null}
        </div>

        <div className="catalog-review-tags">
          {displayGender ? (
            <button
              type="button"
              className={genderChipClass(displayGender)}
              onClick={() => onDraftChange({ ...draft, gender: displayGender })}
            >
              {displayGender}
            </button>
          ) : (
            <span className="review-tag review-tag--muted">gender ?</span>
          )}
          {chips
            .filter((chip) => chip.group !== "gender")
            .map((chip) => (
              <button
                key={chip.key}
                type="button"
                className={`review-tag${enabledTags.has(chip.key) ? " review-tag--enabled" : ""}`}
                onClick={() => onToggleTag(chip.key)}
              >
                {chip.label}
              </button>
            ))}
        </div>

        <div className="catalog-review-prompt" title={finalPrompt || undefined}>
          {finalPrompt || item.generation_prompt || "—"}
        </div>
      </aside>
    </article>
  );
}

export function createDraftForItem(item: CatalogReviewItem): CharacterDraft {
  const chips = appearanceTagChips(item);
  const coverIndex = item.images.findIndex((image) => image.is_cover || image.id === item.cover_image_id);
  return {
    imageIndex: coverIndex >= 0 ? coverIndex : 0,
    gender: item.gender,
    rating: item.rating,
    enabledTags: defaultEnabledTagKeys(chips),
  };
}
