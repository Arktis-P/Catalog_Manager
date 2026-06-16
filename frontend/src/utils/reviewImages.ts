export function pendingReviewImageUrl(imagePath: string | null | undefined): string | null {
  if (!imagePath) {
    return null;
  }
  const filename = imagePath.split(/[\\/]/).pop();
  return filename ? `/media/pending-review/${filename}` : null;
}
