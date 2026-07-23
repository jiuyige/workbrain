import {
  type FormEvent,
  useCallback,
  useEffect,
  useRef,
  useState,
} from "react";

import { getApiErrorMessage } from "../api/errorMessage";
import {
  archiveKnowledgeBaseDocument,
  type BackgroundJob,
  type DocumentChunk,
  type DocumentContent,
  getBackgroundJob,
  getDocumentContent,
  type KnowledgeDocument,
  listDocumentChunks,
  listKnowledgeBaseDocuments,
  publishKnowledgeBaseDocument,
  uploadKnowledgeBaseDocument,
} from "../document/api";
import { listKnowledgeBases, type KnowledgeBase } from "../knowledgeBase/api";
import { useOrganization } from "../organization/OrganizationContext";

const terminalJobStatuses = new Set(["succeeded", "failed", "cancelled"]);

const documentStatusLabels: Record<string, string> = {
  uploaded: "已上传",
  processing: "处理中",
  ready: "待发布",
  published: "已发布",
  archived: "已归档",
};

const jobStatusLabels: Record<string, string> = {
  queued: "等待处理",
  running: "正在解析和向量化",
  succeeded: "处理成功",
  failed: "处理失败",
  cancelled: "处理已取消",
};

export function DocumentsPage() {
  const { activeOrganization } = useOrganization();
  const [knowledgeBases, setKnowledgeBases] = useState<KnowledgeBase[]>([]);
  const [knowledgeBaseId, setKnowledgeBaseId] = useState<number | null>(null);
  const [documents, setDocuments] = useState<KnowledgeDocument[]>([]);
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [activeJob, setActiveJob] = useState<BackgroundJob | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [isUploading, setIsUploading] = useState(false);
  const [pendingActionId, setPendingActionId] = useState<number | null>(null);
  const [errorMessage, setErrorMessage] = useState("");
  const [documentContent, setDocumentContent] =
    useState<DocumentContent | null>(null);
  const [documentChunks, setDocumentChunks] = useState<DocumentChunk[] | null>(
    null,
  );
  const fileInputRef = useRef<HTMLInputElement>(null);

  const loadDocuments = useCallback(async (selectedKnowledgeBaseId: number) => {
    const items = await listKnowledgeBaseDocuments(selectedKnowledgeBaseId);
    setDocuments(items);
  }, []);

  useEffect(() => {
    setKnowledgeBases([]);
    setKnowledgeBaseId(null);
    setDocuments([]);
    setSelectedFile(null);
    setActiveJob(null);
    setDocumentContent(null);
    setDocumentChunks(null);
    setErrorMessage("");

    if (!activeOrganization) {
      return;
    }

    let isActive = true;
    setIsLoading(true);
    listKnowledgeBases()
      .then((items) => {
        if (isActive) {
          setKnowledgeBases(items);
          setKnowledgeBaseId(items[0]?.id ?? null);
        }
      })
      .catch((error) => {
        if (isActive) {
          setErrorMessage(getApiErrorMessage(error));
        }
      })
      .finally(() => {
        if (isActive) {
          setIsLoading(false);
        }
      });

    return () => {
      isActive = false;
    };
  }, [activeOrganization?.id]);

  useEffect(() => {
    if (knowledgeBaseId === null) {
      return;
    }

    let isActive = true;
    setIsLoading(true);
    setDocuments([]);
    setDocumentContent(null);
    setDocumentChunks(null);
    loadDocuments(knowledgeBaseId)
      .catch((error) => {
        if (isActive) {
          setErrorMessage(getApiErrorMessage(error));
        }
      })
      .finally(() => {
        if (isActive) {
          setIsLoading(false);
        }
      });

    return () => {
      isActive = false;
    };
  }, [knowledgeBaseId, loadDocuments]);

  useEffect(() => {
    if (!activeJob || terminalJobStatuses.has(activeJob.status)) {
      return;
    }

    const activeJobId = activeJob.id;
    let isActive = true;

    async function refreshJob() {
      try {
        const job = await getBackgroundJob(activeJobId);
        if (!isActive) {
          return;
        }
        setActiveJob(job);
        if (job.status === "succeeded" && knowledgeBaseId !== null) {
          await loadDocuments(knowledgeBaseId);
        }
      } catch (error) {
        if (isActive) {
          setErrorMessage(getApiErrorMessage(error));
        }
      }
    }

    void refreshJob();
    const intervalId = window.setInterval(() => void refreshJob(), 2000);
    return () => {
      isActive = false;
      window.clearInterval(intervalId);
    };
  }, [activeJob?.id, activeJob?.status, knowledgeBaseId, loadDocuments]);

  async function handleUpload(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!selectedFile || knowledgeBaseId === null) {
      return;
    }

    setErrorMessage("");
    setIsUploading(true);
    try {
      const response = await uploadKnowledgeBaseDocument(
        knowledgeBaseId,
        selectedFile,
      );
      setDocuments((current) => [
        ...current,
        {
          ...response.document,
          chunk_count: 0,
          embedded_chunk_count: 0,
          published_chunk_count: 0,
          is_ready_for_publish: false,
          is_ready_for_rag: false,
        },
      ]);
      setActiveJob({
        id: response.job.id,
        created_by_user_id: 0,
        job_type: "document_processing",
        status: response.job.status,
        error_message: null,
        attempt_count: 0,
        next_retry_at: null,
        created_at: "",
        started_at: null,
        finished_at: null,
      });
      setSelectedFile(null);
      if (fileInputRef.current) {
        fileInputRef.current.value = "";
      }
    } catch (error) {
      setErrorMessage(getApiErrorMessage(error));
    } finally {
      setIsUploading(false);
    }
  }

  async function refreshDocuments() {
    if (knowledgeBaseId === null) {
      return;
    }
    setErrorMessage("");
    setIsLoading(true);
    try {
      await loadDocuments(knowledgeBaseId);
    } catch (error) {
      setErrorMessage(getApiErrorMessage(error));
    } finally {
      setIsLoading(false);
    }
  }

  async function changeLifecycle(documentId: number, action: "publish" | "archive") {
    if (knowledgeBaseId === null) {
      return;
    }
    setErrorMessage("");
    setPendingActionId(documentId);
    try {
      if (action === "publish") {
        await publishKnowledgeBaseDocument(knowledgeBaseId, documentId);
      } else {
        await archiveKnowledgeBaseDocument(knowledgeBaseId, documentId);
      }
      await loadDocuments(knowledgeBaseId);
    } catch (error) {
      setErrorMessage(getApiErrorMessage(error));
    } finally {
      setPendingActionId(null);
    }
  }

  async function showContent(documentId: number) {
    if (knowledgeBaseId === null) {
      return;
    }
    setErrorMessage("");
    try {
      setDocumentContent(await getDocumentContent(knowledgeBaseId, documentId));
    } catch (error) {
      setErrorMessage(getApiErrorMessage(error));
    }
  }

  async function showChunks(documentId: number) {
    if (knowledgeBaseId === null) {
      return;
    }
    setErrorMessage("");
    try {
      setDocumentChunks(await listDocumentChunks(knowledgeBaseId, documentId));
    } catch (error) {
      setErrorMessage(getApiErrorMessage(error));
    }
  }

  const canApprove =
    activeOrganization?.role === "admin" ||
    activeOrganization?.role === "approver";

  return (
    <section className="management-page">
      <div className="page-heading">
        <p className="eyebrow">企业内容中心</p>
        <h1>文档管理</h1>
        <p>上传资料，跟踪后台处理进度，并控制哪些版本可供 RAG 使用。</p>
      </div>

      {errorMessage && (
        <p className="form-message error" role="alert">
          {errorMessage}
        </p>
      )}

      <article className="content-card document-upload-card">
        <div className="card-heading">
          <div>
            <h2>上传企业文档</h2>
            <p>目前支持 UTF-8 编码的 .txt 和 .md 文本，上传后自动解析、切块和向量化。</p>
          </div>
        </div>
        {knowledgeBases.length === 0 && !isLoading ? (
          <p className="empty-state">请先为当前组织创建知识库</p>
        ) : (
          <form className="inline-form document-upload-form" onSubmit={handleUpload}>
            <label>
              目标知识库
              <select
                value={knowledgeBaseId ?? ""}
                onChange={(event) => setKnowledgeBaseId(Number(event.target.value))}
                disabled={isUploading}
              >
                {knowledgeBases.map((knowledgeBase) => (
                  <option key={knowledgeBase.id} value={knowledgeBase.id}>
                    {knowledgeBase.name}
                  </option>
                ))}
              </select>
            </label>
            <label>
              选择文档
              <input
                ref={fileInputRef}
                type="file"
                accept=".txt,.md,text/plain,text/markdown"
                onChange={(event) => setSelectedFile(event.target.files?.[0] ?? null)}
                required
                disabled={isUploading}
              />
            </label>
            <button type="submit" disabled={!selectedFile || isUploading}>
              {isUploading ? "正在上传…" : "上传并处理"}
            </button>
          </form>
        )}

        {activeJob && (
          <div className={`job-progress job-${activeJob.status}`} aria-live="polite">
            <strong>{jobStatusLabels[activeJob.status] || activeJob.status}</strong>
            <span>后台任务 #{activeJob.id}</span>
            {activeJob.error_message && <p>{activeJob.error_message}</p>}
          </div>
        )}
      </article>

      <article className="content-card">
        <div className="card-heading">
          <div>
            <h2>知识库文档</h2>
            <p>发布后的完整向量分块才会进入企业 RAG 检索范围。</p>
          </div>
          <button
            type="button"
            className="secondary-button"
            onClick={() => void refreshDocuments()}
            disabled={knowledgeBaseId === null || isLoading}
          >
            刷新状态
          </button>
        </div>

        {isLoading ? (
          <p className="empty-state">正在加载文档…</p>
        ) : documents.length === 0 ? (
          <p className="empty-state">当前知识库还没有文档</p>
        ) : (
          <div className="document-list">
            {documents.map((document) => (
              <article className="document-item" key={document.id}>
                <div className="document-title-row">
                  <div>
                    <h3>{document.filename}</h3>
                    <p>
                      版本 {document.version} · {document.chunk_count} 个分块 · 已向量化 {document.embedded_chunk_count}
                    </p>
                  </div>
                  <span className={`status-badge status-${document.status}`}>
                    {documentStatusLabels[document.status] || document.status}
                  </span>
                </div>
                {document.is_ready_for_rag && (
                  <span className="rag-ready-badge">可用于 RAG</span>
                )}
                <div className="document-actions">
                  <button type="button" className="text-button" onClick={() => void showContent(document.id)}>
                    查看正文
                  </button>
                  <button type="button" className="text-button" onClick={() => void showChunks(document.id)}>
                    查看分块
                  </button>
                  {canApprove && document.is_ready_for_publish && (
                    <button
                      type="button"
                      className="text-button"
                      onClick={() => void changeLifecycle(document.id, "publish")}
                      disabled={pendingActionId === document.id}
                    >
                      发布
                    </button>
                  )}
                  {canApprove && document.status === "published" && (
                    <button
                      type="button"
                      className="text-button danger"
                      onClick={() => void changeLifecycle(document.id, "archive")}
                      disabled={pendingActionId === document.id}
                    >
                      归档
                    </button>
                  )}
                </div>
              </article>
            ))}
          </div>
        )}
      </article>

      {(documentContent || documentChunks) && (
        <div className="content-grid two-columns document-detail-grid">
          {documentContent && (
            <article className="content-card document-preview">
              <div className="card-heading">
                <div>
                  <h2>提取正文</h2>
                  <p>{documentContent.filename}</p>
                </div>
              </div>
              <pre>{documentContent.content}</pre>
            </article>
          )}
          {documentChunks && (
            <article className="content-card document-preview">
              <div className="card-heading">
                <div>
                  <h2>文档分块</h2>
                  <p>按进入向量检索的最小内容单元查看。</p>
                </div>
              </div>
              <div className="chunk-list">
                {documentChunks.map((chunk) => (
                  <section key={chunk.id}>
                    <strong>分块 #{chunk.chunk_index + 1} · {chunk.char_count} 字符</strong>
                    <p>{chunk.content}</p>
                  </section>
                ))}
              </div>
            </article>
          )}
        </div>
      )}
    </section>
  );
}
