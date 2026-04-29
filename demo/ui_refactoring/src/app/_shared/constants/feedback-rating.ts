export enum FeedbackRating {
    None = 0,
    Positive = 1,
    Negative = 2,
    Neutral = 3
}

const RATING_LABEL: Readonly<Record<FeedbackRating, string>> = {
  [FeedbackRating.None]: '—',
  [FeedbackRating.Positive]: 'Helpful',
  [FeedbackRating.Negative]: 'Not Helpful',
  [FeedbackRating.Neutral]: 'Neutral',
} as const;

export function getRatingLabel(rating: FeedbackRating): string {
     return RATING_LABEL[rating] ?? '—';
}
