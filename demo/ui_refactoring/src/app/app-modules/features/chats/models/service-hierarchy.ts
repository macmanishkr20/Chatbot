import { HierarchyType } from "../../../../_shared/constants/hierarchy-type";

export interface ServiceHierarchyVM {
    id: number;
    description: string | null;
    hierarchyType: HierarchyType;
    parentId: number | null;
    parent: ServiceHierarchyVM | null;
    children: ServiceHierarchyVM[];
}

export interface HierarchyDTO {
    id: number;
    name: string | null;
}