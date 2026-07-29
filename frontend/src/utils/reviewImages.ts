function imageSubdir(imagePath: string): "pending_review" | "catalog_selected" {
  return imagePath.replace(/\\/g, "/").includes("/catalog_selected/") ? "catalog_selected" : "pending_review";
}

const DANBOORU_IMAGE_HOSTS = new Set(["danbooru.donmai.us", "cdn.donmai.us"]);

export function referenceReviewImageUrl(raw: string | null | undefined): string | null {
  const trimmed = raw?.trim();
  if (!trimmed) {
    return null;
  }
  if (trimmed.startsWith("/api/wiki-proxy-image?")) {
    return trimmed;
  }

  const normalized = trimmed.startsWith("//") ? `https:${trimmed}` : trimmed;
  let url: URL;
  try {
    url = new URL(normalized);
  } catch {
    return null;
  }

  if ((url.protocol !== "http:" && url.protocol !== "https:") || !DANBOORU_IMAGE_HOSTS.has(url.hostname)) {
    return null;
  }

  return `/api/wiki-proxy-image?url=${encodeURIComponent(url.toString())}`;
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
