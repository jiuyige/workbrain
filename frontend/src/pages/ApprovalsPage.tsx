import { type FormEvent, useEffect, useRef, useState } from "react";

import { getApiErrorMessage } from "../api/errorMessage";
import { useAuth } from "../auth/AuthContext";
import { useOrganization } from "../organization/OrganizationContext";
import {
  approveServiceRequest,
  listServiceRequests,
  rejectServiceRequest,
  type ServiceRequest,
} from "../serviceRequest/api";

function formatDateTime(value: string): string {
  return new Intl.DateTimeFormat("zh-CN", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(value));
}

export function ApprovalsPage() {
  const { currentUser } = useAuth();
  const { activeOrganization } = useOrganization();
  const [requests, setRequests] = useState<ServiceRequest[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [pendingActionId, setPendingActionId] = useState<number | null>(null);
  const [rejectingRequest, setRejectingRequest] =
    useState<ServiceRequest | null>(null);
  const [rejectReason, setRejectReason] = useState("");
  const [errorMessage, setErrorMessage] = useState("");
  const [successMessage, setSuccessMessage] = useState("");
  const activeOrganizationIdRef = useRef<number | null>(null);

  const canApprove =
    activeOrganization?.role === "approver" ||
    activeOrganization?.role === "admin";

  useEffect(() => {
    const organizationId = activeOrganization?.id ?? null;
    activeOrganizationIdRef.current = organizationId;
    setRequests([]);
    setRejectingRequest(null);
    setRejectReason("");
    setErrorMessage("");
    setSuccessMessage("");
    setPendingActionId(null);

    if (!organizationId || !canApprove) {
      setIsLoading(false);
      return;
    }

    let isActive = true;
    setIsLoading(true);
    listServiceRequests("pending")
      .then((items) => {
        if (isActive) {
          setRequests(items);
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
  }, [activeOrganization?.id, canApprove]);

  async function approveRequest(request: ServiceRequest) {
    if (!activeOrganization || request.requester_user_id === currentUser?.id) {
      return;
    }
    const organizationId = activeOrganization.id;
    setPendingActionId(request.id);
    setErrorMessage("");
    setSuccessMessage("");
    try {
      await approveServiceRequest(request.id);
      if (activeOrganizationIdRef.current !== organizationId) {
        return;
      }
      setRequests((items) => items.filter((item) => item.id !== request.id));
      setSuccessMessage(`申请 #${request.id} 已批准。`);
    } catch (error) {
      if (activeOrganizationIdRef.current === organizationId) {
        setErrorMessage(getApiErrorMessage(error));
      }
    } finally {
      if (activeOrganizationIdRef.current === organizationId) {
        setPendingActionId(null);
      }
    }
  }

  async function submitRejection(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (
      !activeOrganization ||
      !rejectingRequest ||
      rejectingRequest.requester_user_id === currentUser?.id
    ) {
      return;
    }
    const organizationId = activeOrganization.id;
    const requestId = rejectingRequest.id;
    setPendingActionId(requestId);
    setErrorMessage("");
    setSuccessMessage("");
    try {
      await rejectServiceRequest(requestId, rejectReason.trim());
      if (activeOrganizationIdRef.current !== organizationId) {
        return;
      }
      setRequests((items) => items.filter((item) => item.id !== requestId));
      setRejectingRequest(null);
      setRejectReason("");
      setSuccessMessage(`申请 #${requestId} 已拒绝。`);
    } catch (error) {
      if (activeOrganizationIdRef.current === organizationId) {
        setErrorMessage(getApiErrorMessage(error));
      }
    } finally {
      if (activeOrganizationIdRef.current === organizationId) {
        setPendingActionId(null);
      }
    }
  }

  return (
    <section className="management-page approvals-page">
      <div className="page-heading">
        <div>
          <p className="eyebrow">IT 服务流程</p>
          <h1>申请审批</h1>
          <p>审批当前组织内的待处理申请，并为拒绝决定留下原因。</p>
        </div>
      </div>

      {!canApprove ? (
        <article className="content-card approval-permission-card">
          <h2>没有审批权限</h2>
          <p>只有审批人或管理员可以处理服务申请。</p>
        </article>
      ) : (
        <>
          {errorMessage && (
            <p className="form-message error" role="alert">
              {errorMessage}
            </p>
          )}
          {successMessage && (
            <p className="form-message success" role="status">
              {successMessage}
            </p>
          )}

          <article className="content-card approval-queue-card">
            <div className="card-heading approval-heading">
              <div>
                <h2>待审批队列</h2>
                <p>{activeOrganization?.name ?? "当前组织"}</p>
              </div>
              <span className="approval-count">{requests.length} 条待处理</span>
            </div>

            {isLoading ? (
              <p className="empty-state">正在加载待审批申请…</p>
            ) : requests.length === 0 ? (
              <p className="empty-state">当前组织没有待审批申请</p>
            ) : (
              <div className="approval-list">
                {requests.map((request) => {
                  const isOwnRequest =
                    request.requester_user_id === currentUser?.id;
                  const isPending = pendingActionId === request.id;
                  return (
                    <article className="approval-item" key={request.id}>
                      <div className="approval-item-heading">
                        <div>
                          <small>申请 #{request.id}</small>
                          <h3>{request.title}</h3>
                        </div>
                        <span className="status-badge status-pending">
                          待审批
                        </span>
                      </div>
                      <dl className="approval-metadata">
                        <div>
                          <dt>服务项目</dt>
                          <dd>#{request.service_catalog_item_id}</dd>
                        </div>
                        <div>
                          <dt>申请人</dt>
                          <dd>用户 #{request.requester_user_id}</dd>
                        </div>
                        <div>
                          <dt>提交时间</dt>
                          <dd>{formatDateTime(request.created_at)}</dd>
                        </div>
                      </dl>
                      <p className="approval-description">
                        {request.description}
                      </p>

                      {isOwnRequest ? (
                        <p className="approval-self-notice">
                          不能审批自己提交的申请。
                        </p>
                      ) : (
                        <div className="approval-actions">
                          <button
                            type="button"
                            className="approval-approve-button"
                            aria-label={`批准申请 #${request.id}`}
                            disabled={isPending || pendingActionId !== null}
                            onClick={() => void approveRequest(request)}
                          >
                            {isPending ? "处理中…" : "批准"}
                          </button>
                          <button
                            type="button"
                            className="approval-reject-button"
                            aria-label={`拒绝申请 #${request.id}`}
                            disabled={pendingActionId !== null}
                            onClick={() => {
                              setRejectingRequest(request);
                              setRejectReason("");
                              setErrorMessage("");
                              setSuccessMessage("");
                            }}
                          >
                            拒绝
                          </button>
                        </div>
                      )}
                    </article>
                  );
                })}
              </div>
            )}
          </article>

          {rejectingRequest && (
            <form className="content-card rejection-form" onSubmit={submitRejection}>
              <div className="card-heading">
                <div>
                  <h2>拒绝申请 #{rejectingRequest.id}</h2>
                  <p>{rejectingRequest.title}</p>
                </div>
              </div>
              <label>
                拒绝原因
                <textarea
                  value={rejectReason}
                  onChange={(event) => setRejectReason(event.target.value)}
                  maxLength={1000}
                  required
                  autoFocus
                />
              </label>
              <div className="approval-actions">
                <button
                  type="submit"
                  className="approval-reject-button"
                  disabled={pendingActionId !== null || !rejectReason.trim()}
                >
                  {pendingActionId === rejectingRequest.id
                    ? "正在拒绝…"
                    : "确认拒绝"}
                </button>
                <button
                  type="button"
                  className="secondary-button"
                  disabled={pendingActionId !== null}
                  onClick={() => {
                    setRejectingRequest(null);
                    setRejectReason("");
                  }}
                >
                  取消
                </button>
              </div>
            </form>
          )}
        </>
      )}
    </section>
  );
}
