import { useEffect } from "react";

interface ReviewImageLightboxProps {
  src: string;
  alt: string;
  onClose: () => void;
}

export function ReviewImageLightbox({ src, alt, onClose }: ReviewImageLightboxProps) {
  useEffect(() => {
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";

    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        onClose();
      }
    };

    window.addEventListener("keydown", onKeyDown);
    return () => {
      document.body.style.overflow = previousOverflow;
      window.removeEventListener("keydown", onKeyDown);
    };
  }, [onClose]);

  return (
    <div className="review-lightbox" role="dialog" aria-modal="true" aria-label={alt} onClick={onClose}>
      <button type="button" className="review-lightbox-close btn btn-small" onClick={onClose}>
        Close
      </button>
      <div className="review-lightbox-content" onClick={(event) => event.stopPropagation()}>
        <img src={src} alt={alt} />
      </div>
    </div>
  );
}
