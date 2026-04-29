import { FeedbackRating } from "../../../../_shared/constants/feedback-rating";
import { MessageFeedbackVM } from "../../chats/models/message-feedabck";

export interface FeedbackGridVM extends MessageFeedbackVM {
  topic?: string;
  functionName?: string;
}

export interface DashboardSummaryItem {
    label: string;
    value: number;
    sortId: number;
}

export interface DashboardVM {
    rating: FeedbackRating;
    totalCount: number;
    monthId: number;
    monthName: string;
    year: number;
}

export interface DashboardData {
    feedbackByCategory: DashboardVM[];
    feedbackByMonth: DashboardVM[];
    messageFeedbacks: FeedbackGridVM[];
}

export interface MonthEntry {
  label: string;      // short display label e.g. "Jan '26"
  fullMonthName: string;
  year: number;
  monthId: number;
}