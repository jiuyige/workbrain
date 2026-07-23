import { type FormEvent, useEffect, useState } from "react";

import { getApiErrorMessage } from "../api/errorMessage";
import {
  createKnowledgeBase,
  listKnowledgeBases,
  type KnowledgeBase,
  updateKnowledgeBase,
} from "../knowledgeBase/api";
import { useOrganization } from "../organization/OrganizationContext";

export function KnowledgeBasesPage() {
  const { activeOrganization, isLoading: isOrganizationLoading } =
    useOrganization();
  const [knowledgeBases, setKnowledgeBases] = useState<KnowledgeBase[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [errorMessage, setErrorMessage] = useState("");
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [editingId, setEditingId] = useState<number | null>(null);

  useEffect(() => {
    setKnowledgeBases([]);
    setErrorMessage("");
    setEditingId(null);
    if (!activeOrganization) {
      return;
    }

    let isActive = true;
    setIsLoading(true);
    listKnowledgeBases()
      .then((items) => {
        if (isActive) {
          setKnowledgeBases(items);
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

  function resetForm() {
    setName("");
    setDescription("");
    setEditingId(null);
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setErrorMessage("");
    setIsSubmitting(true);
    try {
      const saved = editingId
        ? await updateKnowledgeBase(
            editingId,
            name.trim(),
            description.trim(),
          )
        : await createKnowledgeBase(name.trim(), description.trim());
      setKnowledgeBases((current) => {
        const withoutSaved = current.filter((item) => item.id !== saved.id);
        return [...withoutSaved, saved].sort((a, b) =>
          a.name.localeCompare(b.name),
        );
      });
      resetForm();
    } catch (error) {
      setErrorMessage(getApiErrorMessage(error));
    } finally {
      setIsSubmitting(false);
    }
  }

  function startEditing(knowledgeBase: KnowledgeBase) {
    setEditingId(knowledgeBase.id);
    setName(knowledgeBase.name);
    setDescription(knowledgeBase.description || "");
  }

  const canManage = activeOrganization?.role === "admin";

  return (
    <section className="management-page">
      <div className="page-heading">
        <p className="eyebrow">企业内容中心</p>
        <h1>企业知识库</h1>
        <p>当前组织：{activeOrganization?.name || "正在加载"}</p>
      </div>

      {errorMessage && (
        <p className="form-message error" role="alert">
          {errorMessage}
        </p>
      )}

      {canManage && (
        <article className="content-card knowledge-form-card">
          <div className="card-heading">
            <div>
              <h2>{editingId ? "编辑知识库" : "创建知识库"}</h2>
              <p>在文档管理中上传、处理并发布知识库文档。</p>
            </div>
          </div>
          <form className="inline-form knowledge-form" onSubmit={handleSubmit}>
            <label>
              知识库名称
              <input
                value={name}
                onChange={(event) => setName(event.target.value)}
                maxLength={100}
                required
                disabled={isSubmitting}
              />
            </label>
            <label className="wide-field">
              知识库说明
              <input
                value={description}
                onChange={(event) => setDescription(event.target.value)}
                maxLength={1000}
                disabled={isSubmitting}
              />
            </label>
            <button type="submit" disabled={isSubmitting}>
              {editingId ? "保存修改" : "创建知识库"}
            </button>
            {editingId && (
              <button
                type="button"
                className="secondary-button"
                onClick={resetForm}
              >
                取消
              </button>
            )}
          </form>
        </article>
      )}

      <div className="knowledge-grid">
        {isOrganizationLoading || isLoading ? (
          <p className="empty-state">正在加载知识库…</p>
        ) : knowledgeBases.length === 0 ? (
          <p className="empty-state">当前知识库为空</p>
        ) : (
          knowledgeBases.map((knowledgeBase) => (
            <article className="knowledge-card" key={knowledgeBase.id}>
              <div>
                <span className="role-badge">知识库</span>
                <h2>{knowledgeBase.name}</h2>
                <p>{knowledgeBase.description || "暂无说明"}</p>
              </div>
              <footer>
                <span>编号 #{knowledgeBase.id}</span>
                {canManage && (
                  <button
                    type="button"
                    className="text-button"
                    onClick={() => startEditing(knowledgeBase)}
                  >
                    编辑
                  </button>
                )}
              </footer>
            </article>
          ))
        )}
      </div>
    </section>
  );
}
