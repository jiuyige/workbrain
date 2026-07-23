import { apiRequest } from "../api/client";
import type { ServiceRequest } from "../serviceRequest/api";

export interface ServiceAgentCatalogItem {
  id: number;
  name: string;
  description: string;
}

export interface ServiceAgentResult {
  items?: ServiceAgentCatalogItem[];
  requests?: ServiceRequest[];
  missing_fields?: string[];
  candidates?: ServiceAgentCatalogItem[];
  requires_confirmation?: boolean;
  confirmation_token?: string;
  service?: Pick<ServiceAgentCatalogItem, "id" | "name">;
  title?: string;
  description?: string;
  created?: boolean;
  service_request?: ServiceRequest;
}

export interface ServiceAgentResponse {
  action: string;
  reply: string;
  result: ServiceAgentResult;
}

export function sendServiceAgentMessage(
  message: string,
): Promise<ServiceAgentResponse> {
  return apiRequest<ServiceAgentResponse>("/assistant/service-tools", {
    method: "POST",
    body: JSON.stringify({ message }),
  });
}

export function confirmServiceAgentRequest(
  confirmationToken: string,
): Promise<ServiceAgentResponse> {
  return apiRequest<ServiceAgentResponse>("/assistant/service-tools/confirm", {
    method: "POST",
    body: JSON.stringify({ confirmation_token: confirmationToken }),
  });
}
