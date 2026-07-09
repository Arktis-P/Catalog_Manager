function imageSubdir(imagePath: string): "pending_review" | "catalog_selected" {
  return imagePath.replace(/\\/g, "/").includes("/catalog_selected/") ? "catalog_selected" : "pending_review";
}

export function pendingReviewImageUrl(
  imagePath: string | null | undefined,
  options?: { thumbnail?: boolean; thumbSize?: number },
): string | null {
  if (!imagePath) {
    return null;
  }
  const filename = imagePath.split(/[\\/]/).pop();
  if (!filename) {
    return null;
  }
  const subdir = imageSubdir(imagePath);
  if (options?.thumbnail) {
    const size = options.thumbSize ?? 384;
    return `/api/media/thumb/${subdir}/${encodeURIComponent(filename)}?size=${size}`;
  }
  const staticSubdir = subdir === "catalog_selected" ? "catalog-selected" : "pending-review";
  return `/media/${staticSubdir}/${filename}`;
}

export function catalogCoverImageUrl(imagePath: string | null | undefined, thumbSize = 384): string | null {
  return pendingReviewImageUrl(imagePath, { thumbnail: true, thumbSize });
}
