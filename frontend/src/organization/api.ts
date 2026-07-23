import { apiRequest } from "../api/client";

export type OrganizationRole = "member" | "approver" | "admin";

export interface Organization {
  id: number;
  name: string;
  slug: string;
  role: OrganizationRole;
  created_at: string;
}

export interface OrganizationMember {
  id: number;
  user_id: number;
  username: string;
  role: OrganizationRole;
  is_active: boolean;
  created_at: string;
}

export async function listOrganizations(): Promise<Organization[]> {
  const response = await apiRequest<{ organizations: Organization[] }>(
    "/organizations",
  );
  return response.organizations;
}

export function createOrganization(
  name: string,
  slug: string,
): Promise<Organization> {
  return apiRequest<Organization>("/organizations", {
    method: "POST",
    body: JSON.stringify({ name, slug }),
  });
}

export async function listOrganizationMembers(): Promise<OrganizationMember[]> {
  const response = await apiRequest<{ members: OrganizationMember[] }>(
    "/organizations/members",
  );
  return response.members;
}

export function inviteOrganizationMember(
  username: string,
  role: OrganizationRole,
): Promise<OrganizationMember> {
  return apiRequest<OrganizationMember>("/organizations/members", {
    method: "POST",
    body: JSON.stringify({ username, role }),
  });
}

export function disableOrganizationMember(
  membershipId: number,
): Promise<OrganizationMember> {
  return apiRequest<OrganizationMember>(
    `/organizations/members/${membershipId}/disable`,
    { method: "PATCH" },
  );
}
