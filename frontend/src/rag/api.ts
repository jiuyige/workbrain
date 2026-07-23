import { apiRequest } from "../api/client";

export interface RAGSource {
  reference: string;
  document_id: number;
  chunk_id: number;
  chunk_index: number;
  score: number;
  semantic_score: number;
  lexical_score: number;
  preview: string;
}

export interface RAGRetrieval {
  top_score: number | null;
  min_score: number;
  matched_count: number;
}

export interface RAGAnswer {
  answer: string;
  sources: RAGSource[];
  rag_query_log_id: number;
  retrieval: RAGRetrieval;
}

export function askKnowledgeBase(
  knowledgeBaseId: number,
  question: string,
): Promise<RAGAnswer> {
  return apiRequest<RAGAnswer>(
    `/rag/knowledge-bases/${knowledgeBaseId}/ask`,
    {
      method: "POST",
      body: JSON.stringify({ question }),
    },
  );
}
