import type { Series } from "../types";

export function sortSeriesForGeneration(items: Series[]): Series[] {
  return [...items].sort((left, right) => {
    const leftDone = left.generation_pipeline_done ? 1 : 0;
    const rightDone = right.generation_pipeline_done ? 1 : 0;
    if (leftDone !== rightDone) {
      return leftDone - rightDone;
    }
    if (right.post_count !== left.post_count) {
      return right.post_count - left.post_count;
    }
    return left.series_tag.localeCompare(right.series_tag);
  });
}
