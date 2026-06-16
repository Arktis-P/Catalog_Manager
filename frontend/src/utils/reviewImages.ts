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
  if (options?.thumbnail) {
    const size = options.thumbSize ?? 384;
    return `/api/media/thumb/${encodeURIComponent(filename)}?size=${size}`;
  }
  return `/media/pending-review/${filename}`;
}

export function catalogCoverImageUrl(imagePath: string | null | undefined, thumbSize = 384): string | null {
  return pendingReviewImageUrl(imagePath, { thumbnail: true, thumbSize });
}
