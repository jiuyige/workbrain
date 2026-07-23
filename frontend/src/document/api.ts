import { apiRequest } from "../api/client";

export type DocumentStatus =
  | "uploaded"
  | "processing"
  | "ready"
  | "published"
  | "archived";

export interface KnowledgeDocument {
  id: number;
  owner_id: number;
  organization_id: number;
  knowledge_base_id: number;
  filename: string;
  content_type: string | null;
  version: number;
  status: DocumentStatus;
  chunk_count: number;
  embedded_chunk_count: number;
  published_chunk_count: number;
  is_ready_for_publish: boolean;
  is_ready_for_rag: boolean;
}

interface UploadedDocument {
  id: number;
  owner_id: number;
  organization_id: number;
  knowledge_base_id: number;
  filename: string;
  content_type: string | null;
  version: number;
  status: DocumentStatus;
}

export interface BackgroundJob {
  id: number;
  created_by_user_id: number;
  job_type: string;
  status: string;
  error_message: string | null;
  attempt_count: number;
  next_retry_at: string | null;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
}

interface UploadDocumentResponse {
  message: string;
  document: UploadedDocument;
  job: Pick<BackgroundJob, "id" | "status">;
}

export interface DocumentContent {
  id: number;
  filename: string;
  content: string;
  version: number;
  status: DocumentStatus;
}

export interface DocumentChunk {
  id: number;
  chunk_index: number;
  content: string;
  char_count: number;
  document_version: number;
  status: string;
}

export async function listKnowledgeBaseDocuments(
  knowledgeBaseId: number,
): Promise<KnowledgeDocument[]> {
  const response = await apiRequest<{ documents: KnowledgeDocument[] }>(
    `/knowledge-bases/${knowledgeBaseId}/documents`,
  );
  return response.documents;
}

export function uploadKnowledgeBaseDocument(
  knowledgeBaseId: number,
  file: File,
): Promise<UploadDocumentResponse> {
  const formData = new FormData();
  formData.append("file", file);
  return apiRequest<UploadDocumentResponse>(
    `/knowledge-bases/${knowledgeBaseId}/documents`,
    { method: "POST", body: formData },
  );
}

export function getBackgroundJob(jobId: number): Promise<BackgroundJob> {
  return apiRequest<BackgroundJob>(`/jobs/${jobId}`);
}

export async function getDocumentContent(
  knowledgeBaseId: number,
  documentId: number,
): Promise<DocumentContent> {
  const response = await apiRequest<{ document: DocumentContent }>(
    `/knowledge-bases/${knowledgeBaseId}/documents/${documentId}/content`,
  );
  return response.document;
}

export async function listDocumentChunks(
  knowledgeBaseId: number,
  documentId: number,
): Promise<DocumentChunk[]> {
  const response = await apiRequest<{ chunks: DocumentChunk[] }>(
    `/knowledge-bases/${knowledgeBaseId}/documents/${documentId}/chunks`,
  );
  return response.chunks;
}

export function publishKnowledgeBaseDocument(
  knowledgeBaseId: number,
  documentId: number,
): Promise<void> {
  return apiRequest(
    `/knowledge-bases/${knowledgeBaseId}/documents/${documentId}/publish`,
    { method: "POST" },
  );
}

export function archiveKnowledgeBaseDocument(
  knowledgeBaseId: number,
  documentId: number,
): Promise<void> {
  return apiRequest(
    `/knowledge-bases/${knowledgeBaseId}/documents/${documentId}/archive`,
    { method: "POST" },
  );
}
