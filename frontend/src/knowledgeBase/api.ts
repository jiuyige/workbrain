import { apiRequest } from "../api/client";

export interface KnowledgeBase {
  id: number;
  organization_id: number;
  created_by_user_id: number;
  name: string;
  description: string | null;
  created_at: string;
  updated_at: string;
}

export async function listKnowledgeBases(): Promise<KnowledgeBase[]> {
  const response = await apiRequest<{ knowledge_bases: KnowledgeBase[] }>(
    "/knowledge-bases",
  );
  return response.knowledge_bases;
}

export function createKnowledgeBase(
  name: string,
  description: string,
): Promise<KnowledgeBase> {
  return apiRequest<KnowledgeBase>("/knowledge-bases", {
    method: "POST",
    body: JSON.stringify({ name, description: description || null }),
  });
}

export function updateKnowledgeBase(
  knowledgeBaseId: number,
  name: string,
  description: string,
): Promise<KnowledgeBase> {
  return apiRequest<KnowledgeBase>(`/knowledge-bases/${knowledgeBaseId}`, {
    method: "PATCH",
    body: JSON.stringify({ name, description: description || null }),
  });
}
