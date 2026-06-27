export function normalizeSeriesTag(tag: string): string {
  return tag.toLowerCase().replace(/[\s_\-:/()[\]{}]/g, "");
}
