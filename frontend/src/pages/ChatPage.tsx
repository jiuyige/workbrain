import { type FormEvent, useEffect, useRef, useState } from "react";

import { getApiErrorMessage } from "../api/errorMessage";
import { listKnowledgeBases, type KnowledgeBase } from "../knowledgeBase/api";
import { useOrganization } from "../organization/OrganizationContext";
import { askKnowledgeBase, type RAGAnswer } from "../rag/api";

interface UserMessage {
  id: number;
  role: "user";
  content: string;
}

interface AssistantMessage {
  id: number;
  role: "assistant";
  content: string;
  result: RAGAnswer;
}

type ChatMessage = UserMessage | AssistantMessage;

export function ChatPage() {
  const { activeOrganization } = useOrganization();
  const [knowledgeBases, setKnowledgeBases] = useState<KnowledgeBase[]>([]);
  const [knowledgeBaseId, setKnowledgeBaseId] = useState<number | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [question, setQuestion] = useState("");
  const [isLoadingKnowledgeBases, setIsLoadingKnowledgeBases] = useState(false);
  const [isAnswering, setIsAnswering] = useState(false);
  const [errorMessage, setErrorMessage] = useState("");
  const messageIdRef = useRef(0);
  const activeKnowledgeBaseIdRef = useRef<number | null>(null);

  useEffect(() => {
    setKnowledgeBases([]);
    setKnowledgeBaseId(null);
    setMessages([]);
    setQuestion("");
    setErrorMessage("");

    if (!activeOrganization) {
      return;
    }

    let isActive = true;
    setIsLoadingKnowledgeBases(true);
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
          setIsLoadingKnowledgeBases(false);
        }
      });

    return () => {
      isActive = false;
    };
  }, [activeOrganization?.id]);

  useEffect(() => {
    activeKnowledgeBaseIdRef.current = knowledgeBaseId;
    setMessages([]);
    setErrorMessage("");
    setIsAnswering(false);
  }, [knowledgeBaseId]);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const normalizedQuestion = question.trim();
    if (!normalizedQuestion || knowledgeBaseId === null || isAnswering) {
      return;
    }

    const submittedKnowledgeBaseId = knowledgeBaseId;
    messageIdRef.current += 1;
    const userMessage: UserMessage = {
      id: messageIdRef.current,
      role: "user",
      content: normalizedQuestion,
    };
    setMessages((current) => [...current, userMessage]);
    setQuestion("");
    setErrorMessage("");
    setIsAnswering(true);

    try {
      const result = await askKnowledgeBase(
        submittedKnowledgeBaseId,
        normalizedQuestion,
      );
      if (activeKnowledgeBaseIdRef.current !== submittedKnowledgeBaseId) {
        return;
      }
      messageIdRef.current += 1;
      const assistantMessage: AssistantMessage = {
        id: messageIdRef.current,
        role: "assistant",
        content: result.answer,
        result,
      };
      setMessages((current) => [...current, assistantMessage]);
    } catch (error) {
      if (activeKnowledgeBaseIdRef.current === submittedKnowledgeBaseId) {
        setErrorMessage(getApiErrorMessage(error));
      }
    } finally {
      if (activeKnowledgeBaseIdRef.current === submittedKnowledgeBaseId) {
        setIsAnswering(false);
      }
    }
  }

  const selectedKnowledgeBase = knowledgeBases.find(
    (item) => item.id === knowledgeBaseId,
  );

  return (
    <section className="management-page rag-chat-page">
      <div className="page-heading rag-page-heading">
        <div>
          <p className="eyebrow">企业知识助手</p>
          <h1>AI 问答</h1>
          <p>答案只来自当前组织已发布的知识库资料，并展示对应引用片段。</p>
        </div>
        {knowledgeBases.length > 0 && (
          <label className="rag-knowledge-selector">
            问答知识库
            <select
              value={knowledgeBaseId ?? ""}
              onChange={(event) => {
                setKnowledgeBaseId(Number(event.target.value));
                setQuestion("");
              }}
              disabled={isAnswering}
            >
              {knowledgeBases.map((knowledgeBase) => (
                <option key={knowledgeBase.id} value={knowledgeBase.id}>
                  {knowledgeBase.name}
                </option>
              ))}
            </select>
          </label>
        )}
      </div>

      {errorMessage && (
        <p className="form-message error" role="alert">
          {errorMessage}
        </p>
      )}

      <article className="content-card rag-chat-card">
        {isLoadingKnowledgeBases ? (
          <p className="empty-state">正在加载知识库…</p>
        ) : !selectedKnowledgeBase ? (
          <p className="empty-state">当前组织还没有知识库，请先创建并发布企业文档。</p>
        ) : (
          <>
            <div className="rag-conversation" aria-live="polite">
              {messages.length === 0 && !isAnswering && (
                <div className="rag-welcome">
                  <span className="brand-mark">AI</span>
                  <div>
                    <h2>向 {selectedKnowledgeBase.name} 提问</h2>
                    <p>例如：VPN 如何申请？报销需要哪些材料？</p>
                  </div>
                </div>
              )}

              {messages.map((message) =>
                message.role === "user" ? (
                  <div className="chat-row user-row" key={message.id}>
                    <div className="chat-bubble user-bubble">{message.content}</div>
                  </div>
                ) : (
                  <div className="chat-row assistant-row" key={message.id}>
                    <div className="assistant-message">
                      <div className="chat-bubble assistant-bubble">
                        {message.content}
                      </div>
                      {message.result.sources.length === 0 ? (
                        <p className="rag-refusal-note">
                          资料不足，未调用大模型生成答案
                        </p>
                      ) : (
                        <section className="rag-sources">
                          <div className="rag-source-heading">
                            <h3>引用来源</h3>
                            <span>
                              命中 {message.result.retrieval.matched_count} 个片段 · 查询记录 #{message.result.rag_query_log_id}
                            </span>
                          </div>
                          <div className="rag-source-list">
                            {message.result.sources.map((source) => (
                              <article className="rag-source-card" key={source.chunk_id}>
                                <div>
                                  <strong>{source.reference}</strong>
                                  <span>相关度 {Math.round(source.score * 100)}%</span>
                                </div>
                                <p>{source.preview}</p>
                                <small>
                                  文档 #{source.document_id} · 分块 #{source.chunk_index + 1}
                                </small>
                              </article>
                            ))}
                          </div>
                        </section>
                      )}
                    </div>
                  </div>
                ),
              )}

              {isAnswering && (
                <div className="chat-row assistant-row">
                  <div className="chat-bubble assistant-bubble loading-bubble">
                    正在检索已发布资料并生成回答…
                  </div>
                </div>
              )}
            </div>

            <form className="rag-question-form" onSubmit={handleSubmit}>
              <label>
                <span>输入问题</span>
                <textarea
                  value={question}
                  onChange={(event) => setQuestion(event.target.value)}
                  placeholder={`向 ${selectedKnowledgeBase.name} 提问`}
                  rows={3}
                  maxLength={2000}
                  disabled={isAnswering}
                  required
                />
              </label>
              <div>
                <small>仅检索当前组织、当前知识库中已发布的文档。</small>
                <button
                  type="submit"
                  disabled={!question.trim() || isAnswering}
                >
                  {isAnswering ? "回答中…" : "发送问题"}
                </button>
              </div>
            </form>
          </>
        )}
      </article>
    </section>
  );
}
