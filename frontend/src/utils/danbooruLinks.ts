const DANBOORU_BASE = "https://danbooru.donmai.us";

export function danbooruPostsUrl(characterTag: string, _seriesTag?: string, fallback?: string | null): string {
  if (fallback) {
    return fallback;
  }
  const tags = encodeURIComponent(`${characterTag} solo`.trim());
  return `${DANBOORU_BASE}/posts?tags=${tags}`;
}

export function danbooruWikiUrl(characterTag: string, fallback?: string | null): string {
  if (fallback) {
    return fallback;
  }
  return `${DANBOORU_BASE}/wiki_pages/${encodeURIComponent(characterTag)}`;
}

export function danbooruSeriesWikiUrl(seriesTag: string): string {
  return `${DANBOORU_BASE}/wiki_pages/${encodeURIComponent(seriesTag)}`;
}

export function openExternal(url: string): void {
  window.open(url, "_blank", "noopener,noreferrer");
}
