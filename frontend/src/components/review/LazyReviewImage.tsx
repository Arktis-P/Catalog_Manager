import { useEffect, useRef, useState } from "react";
import { pendingReviewImageUrl } from "../../utils/reviewImages";

interface LazyReviewImageProps {
  imagePath: string;
  alt: string;
  active?: boolean;
  selected?: boolean;
  previewAnchor?: boolean;
  thumbSize?: number;
  onClick?: () => void;
}

export function LazyReviewImage({
  imagePath,
  alt,
  active = false,
  selected = false,
  previewAnchor = false,
  thumbSize,
  onClick,
}: LazyReviewImageProps) {
  const rootRef = useRef<HTMLButtonElement>(null);
  const [visible, setVisible] = useState(false);
  const src = pendingReviewImageUrl(imagePath, thumbSize ? { thumbnail: true, thumbSize } : undefined);

  useEffect(() => {
    const node = rootRef.current;
    if (!node) {
      return;
    }

    const observer = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          setVisible(entry.isIntersecting);
        }
      },
      { rootMargin: "240px 0px" },
    );

    observer.observe(node);
    return () => observer.disconnect();
  }, []);

  const className = [
    "review-image-slot",
    active ? "review-image-slot--active" : "",
    selected ? "review-image-slot--selected" : "",
  ]
    .filter(Boolean)
    .join(" ");

  return (
    <button
      ref={rootRef}
      type="button"
      className={className}
      onClick={onClick}
      data-preview-anchor={previewAnchor ? "true" : undefined}
      title={`${alt} (Space로 확대)`}
    >
      {visible && src ? (
        <img src={src} alt={alt} loading="lazy" decoding="async" />
      ) : (
        <span className="review-image-placeholder" />
      )}
    </button>
  );
}
