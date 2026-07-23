import { apiRequest } from "../api/client";

export interface ServiceCatalogItem {
  id: number;
  organization_id: number;
  created_by_user_id: number;
  name: string;
  description: string | null;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

export interface Pagination {
  offset: number;
  limit: number;
  total: number;
  returned: number;
}

export async function listActiveServiceCatalogItems(): Promise<
  ServiceCatalogItem[]
> {
  return listServiceCatalogItems(false);
}

export async function listServiceCatalogItems(
  includeInactive: boolean,
): Promise<ServiceCatalogItem[]> {
  const query = includeInactive
    ? "?limit=100&include_inactive=true"
    : "?limit=100";
  const response = await apiRequest<{
    items: ServiceCatalogItem[];
    pagination: Pagination;
  }>(`/service-catalog/items${query}`);
  return response.items;
}

export function createServiceCatalogItem(
  name: string,
  description: string,
): Promise<ServiceCatalogItem> {
  return apiRequest<ServiceCatalogItem>("/service-catalog/items", {
    method: "POST",
    body: JSON.stringify({ name, description }),
  });
}

export function setServiceCatalogItemActive(
  itemId: number,
  isActive: boolean,
): Promise<ServiceCatalogItem> {
  return apiRequest<ServiceCatalogItem>(`/service-catalog/items/${itemId}`, {
    method: "PATCH",
    body: JSON.stringify({ is_active: isActive }),
  });
}
