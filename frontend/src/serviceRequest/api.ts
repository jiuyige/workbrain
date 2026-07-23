import { apiRequest } from "../api/client";

export type ServiceRequestStatus = "pending" | "approved" | "rejected";

export interface ServiceRequest {
  id: number;
  organization_id: number;
  requester_user_id: number;
  service_catalog_item_id: number;
  title: string;
  description: string;
  status: ServiceRequestStatus;
  decided_by_user_id: number | null;
  decision_reason: string | null;
  created_at: string;
  updated_at: string;
  decided_at: string | null;
}

export type ServiceRequestAction = "create" | "approve" | "reject";

export interface ServiceRequestEvent {
  id: number;
  actor_user_id: number;
  action: ServiceRequestAction;
  from_status: ServiceRequestStatus | null;
  to_status: ServiceRequestStatus;
  reason: string | null;
  created_at: string;
}

export async function listServiceRequests(
  status: ServiceRequestStatus | "all" = "all",
): Promise<ServiceRequest[]> {
  const statusQuery = status === "all" ? "" : `&status=${status}`;
  const response = await apiRequest<{
    requests: ServiceRequest[];
  }>(`/service-requests?limit=100${statusQuery}`);
  return response.requests;
}

export function readServiceRequest(requestId: number): Promise<ServiceRequest> {
  return apiRequest<ServiceRequest>(`/service-requests/${requestId}`);
}

export async function listServiceRequestEvents(
  requestId: number,
): Promise<ServiceRequestEvent[]> {
  const response = await apiRequest<{ events: ServiceRequestEvent[] }>(
    `/service-requests/${requestId}/events`,
  );
  return response.events;
}

export function createServiceRequest(
  serviceCatalogItemId: number,
  title: string,
  description: string,
): Promise<ServiceRequest> {
  return apiRequest<ServiceRequest>("/service-requests", {
    method: "POST",
    body: JSON.stringify({
      service_catalog_item_id: serviceCatalogItemId,
      title,
      description,
    }),
  });
}

export function approveServiceRequest(
  requestId: number,
): Promise<ServiceRequest> {
  return apiRequest<ServiceRequest>(`/service-requests/${requestId}/approve`, {
    method: "POST",
  });
}

export function rejectServiceRequest(
  requestId: number,
  reason: string,
): Promise<ServiceRequest> {
  return apiRequest<ServiceRequest>(`/service-requests/${requestId}/reject`, {
    method: "POST",
    body: JSON.stringify({ reason }),
  });
}
