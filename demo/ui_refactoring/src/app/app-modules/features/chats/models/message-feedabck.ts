import { FeedbackRating } from "../../../../_shared/constants/feedback-rating";
import { HierarchyDTO, ServiceHierarchyVM } from "./service-hierarchy";


export interface MessageFeedbackVM {
    id: number;
    userId: number;
    messageId: number;
    rating: FeedbackRating;
    comments?: string;
    createdAt: Date | string;
    modifiedAt?: Date | string;
    category?: number;
    function?: HierarchyDTO;
    subFunction?: HierarchyDTO;
    service?: HierarchyDTO;
}

export interface FeedbackDTO {
    userId: string;
    messageId: string;
    rating: FeedbackRating;
    comments?: string;
    functionId?: number;
    subFunctionId?: number;
    serviceId?: number;
    category?: string;
}

export interface FeedbackResultVM {
    success: boolean;
    message: string;
}

export interface FeedbackFormData {
  rating: FeedbackRating;
  comments?: string;
  category?: string;
  functionId?: number;
  subFunctionId?: number;
  serviceId?: number;
}

export interface FeedbackFormConfig {
  showComments?: boolean;
  showTags?: boolean;
  showCategory?: boolean;
  showServiceHierarchy?: boolean;
  tags?: string[];
  categories?: string[];
  serviceHierarchies?: ServiceHierarchyVM[];
  commentsRequired?: boolean;
  commentsPlaceholder?: string;
  commentsMaxLength?: number;
}