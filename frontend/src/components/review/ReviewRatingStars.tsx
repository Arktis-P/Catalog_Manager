interface ReviewRatingStarsProps {
  rating: number | null;
  onRate: (value: number) => void;
}

function ratingStatusLabel(rating: number | null): { text: string; className: string } {
  if (rating === null) {
    return { text: "미선택", className: "review-rating-status review-rating-status--unset" };
  }
  if (rating === -1) {
    return { text: "-1성", className: "review-rating-status review-rating-status--red" };
  }
  if (rating === 0) {
    return { text: "0성", className: "review-rating-status review-rating-status--zero" };
  }
  return { text: `${rating}성`, className: "review-rating-status review-rating-status--set" };
}

export function ReviewRatingStars({ rating, onRate }: ReviewRatingStarsProps) {
  const status = ratingStatusLabel(rating);

  return (
    <div className="review-rating-stars">
      <button
        type="button"
        className={`review-star review-star--red${rating === -1 ? " review-star--active" : ""}`}
        onClick={() => onRate(-1)}
        aria-label="rating -1"
        title={rating === -1 ? "rating -1 (다시 누르면 해제)" : "rating -1"}
      >
        ★
      </button>
      <button
        type="button"
        className={`review-star review-star--zero${rating === 0 ? " review-star--zero-active" : ""}`}
        onClick={() => onRate(0)}
        aria-label="rating 0"
        title={rating === 0 ? "rating 0 (다시 누르면 해제)" : "rating 0 (이미지 삭제·카탈로그 미표시)"}
      >
        0
      </button>
      {rating !== -1 ? (
        <div className="review-rating-stars-main" aria-label="rating 1-6">
          {Array.from({ length: 6 }, (_, index) => {
            const starValue = index + 1;
            const isYellow = rating !== null && rating > 0 && starValue <= rating;
            const className = [
              "review-star",
              isYellow ? "review-star--yellow review-star--active" : "",
              rating !== null && rating > 0 && !isYellow ? "review-star--black" : "",
              rating === null || rating === 0 ? "review-star--unset" : "",
            ]
              .filter(Boolean)
              .join(" ");

            return (
              <button
                key={starValue}
                type="button"
                className={className}
                onClick={() => onRate(starValue)}
                aria-label={`rating ${starValue}`}
                title={`rating ${starValue}`}
              >
                ★
              </button>
            );
          })}
        </div>
      ) : null}
      <span className={status.className}>{status.text}</span>
    </div>
  );
}

export function toggleRating(current: number | null, next: number): number | null {
  return current === next ? null : next;
}
