interface ReviewImagePreviewProps {
  src: string;
  alt: string;
  top?: number;
  left?: number;
  original?: boolean;
  fitToScreen?: boolean;
  onToggleFit?: () => void;
  onClose?: () => void;
}

export function ReviewImagePreview({
  src,
  alt,
  top = 0,
  left = 0,
  original = false,
  fitToScreen = true,
  onToggleFit,
  onClose,
}: ReviewImagePreviewProps) {
  if (!original) {
    return (
      <div className="review-image-preview" style={{ top, left }} aria-hidden="true">
        <img src={src} alt={alt} decoding="async" />
      </div>
    );
  }

  return (
    <>
      <div className="review-image-preview-original-backdrop" onClick={onClose} />
      <div className="review-image-preview review-image-preview--original" role="dialog" aria-label={alt}>
        <div className="review-image-preview-toolbar">
          {onToggleFit ? (
            <button type="button" className="btn btn-small" onClick={onToggleFit}>
              {fitToScreen ? "실제 크기" : "화면 맞춤"}
            </button>
          ) : null}
        </div>
        <div className="review-image-preview-scroll">
          <img
            src={src}
            alt={alt}
            decoding="async"
            className={fitToScreen ? "review-image-preview-img--fit" : "review-image-preview-img--actual"}
          />
        </div>
      </div>
    </>
  );
}
