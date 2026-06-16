interface ReviewImagePreviewProps {
  src: string;
  alt: string;
  top: number;
  left: number;
}

export function ReviewImagePreview({ src, alt, top, left }: ReviewImagePreviewProps) {
  return (
    <div className="review-image-preview" style={{ top, left }} aria-hidden="true">
      <img src={src} alt={alt} decoding="async" />
    </div>
  );
}
