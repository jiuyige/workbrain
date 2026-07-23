import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";

import { getApiErrorMessage } from "../api/errorMessage";
import { useOrganization } from "../organization/OrganizationContext";
import {
  listServiceRequestEvents,
  listServiceRequests,
  readServiceRequest,
  type ServiceRequest,
  type ServiceRequestAction,
  type ServiceRequestEvent,
  type ServiceRequestStatus,
} from "../serviceRequest/api";

const statusLabels: Record<ServiceRequestStatus, string> = {
  pending: "待审批",
  approved: "已批准",
  rejected: "已拒绝",
};

const actionLabels: Record<ServiceRequestAction, string> = {
  create: "创建申请",
  approve: "批准申请",
  reject: "拒绝申请",
};

function formatDateTime(value: string | null): string {
  if (!value) {
    return "—";
  }
  return new Intl.DateTimeFormat("zh-CN", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(value));
}

export function ServiceRequestsPage() {
  const { activeOrganization } = useOrganization();
  const [statusFilter, setStatusFilter] = useState<
    ServiceRequestStatus | "all"
  >("all");
  const [requests, setRequests] = useState<ServiceRequest[]>([]);
  const [selectedRequest, setSelectedRequest] =
    useState<ServiceRequest | null>(null);
  const [events, setEvents] = useState<ServiceRequestEvent[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [isLoadingDetail, setIsLoadingDetail] = useState(false);
  const [errorMessage, setErrorMessage] = useState("");
  const activeOrganizationIdRef = useRef<number | null>(null);
  const selectedRequestIdRef = useRef<number | null>(null);

  useEffect(() => {
    activeOrganizationIdRef.current = activeOrganization?.id ?? null;
    selectedRequestIdRef.current = null;
    setStatusFilter("all");
    setRequests([]);
    setSelectedRequest(null);
    setEvents([]);
    setIsLoadingDetail(false);
    setErrorMessage("");
  }, [activeOrganization?.id]);

  useEffect(() => {
    const organizationId = activeOrganization?.id;
    if (!organizationId) {
      return;
    }

    let isActive = true;
    setIsLoading(true);
    setSelectedRequest(null);
    setEvents([]);
    setIsLoadingDetail(false);
    selectedRequestIdRef.current = null;
    setErrorMessage("");
    listServiceRequests(statusFilter)
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
  }, [activeOrganization?.id, statusFilter]);

  async function showRequestDetail(requestId: number) {
    if (!activeOrganization) {
      return;
    }
    const organizationId = activeOrganization.id;
    selectedRequestIdRef.current = requestId;
    setSelectedRequest(null);
    setEvents([]);
    setErrorMessage("");
    setIsLoadingDetail(true);
    try {
      const [request, auditEvents] = await Promise.all([
        readServiceRequest(requestId),
        listServiceRequestEvents(requestId),
      ]);
      if (
        activeOrganizationIdRef.current !== organizationId ||
        selectedRequestIdRef.current !== requestId
      ) {
        return;
      }
      setSelectedRequest(request);
      setEvents(auditEvents);
    } catch (error) {
      if (
        activeOrganizationIdRef.current === organizationId &&
        selectedRequestIdRef.current === requestId
      ) {
        setErrorMessage(getApiErrorMessage(error));
      }
    } finally {
      if (
        activeOrganizationIdRef.current === organizationId &&
        selectedRequestIdRef.current === requestId
      ) {
        setIsLoadingDetail(false);
      }
    }
  }

  const isPrivileged =
    activeOrganization?.role === "approver" ||
    activeOrganization?.role === "admin";

  return (
    <section className="management-page service-requests-page">
      <div className="page-heading request-page-heading">
        <div>
          <p className="eyebrow">IT 服务流程</p>
          <h1>我的申请</h1>
          <p>
            {isPrivileged
              ? "查看当前组织内可见的申请记录和完整审计过程。"
              : "跟踪你提交的申请状态和审批结果。"}
          </p>
        </div>
        <Link className="primary-link-button" to="/service-catalog">
          新建申请
        </Link>
      </div>

      {errorMessage && (
        <p className="form-message error" role="alert">
          {errorMessage}
        </p>
      )}

      <div className="request-workspace">
        <article className="content-card request-list-card">
          <div className="card-heading request-list-heading">
            <div>
              <h2>申请记录</h2>
              <p>{isPrivileged ? "当前组织可见申请" : "你提交的申请"}</p>
            </div>
            <label className="request-status-filter">
              申请状态
              <select
                value={statusFilter}
                onChange={(event) =>
                  setStatusFilter(
                    event.target.value as ServiceRequestStatus | "all",
                  )
                }
                disabled={isLoading}
              >
                <option value="all">全部状态</option>
                <option value="pending">待审批</option>
                <option value="approved">已批准</option>
                <option value="rejected">已拒绝</option>
              </select>
            </label>
          </div>

          {isLoading ? (
            <p className="empty-state">正在加载申请…</p>
          ) : requests.length === 0 ? (
            <p className="empty-state">当前筛选条件下没有申请</p>
          ) : (
            <div className="request-list">
              {requests.map((request) => (
                <article
                  className={
                    selectedRequestIdRef.current === request.id
                      ? "request-list-item selected"
                      : "request-list-item"
                  }
                  key={request.id}
                >
                  <div className="request-list-title">
                    <div>
                      <small>申请 #{request.id}</small>
                      <h3>{request.title}</h3>
                    </div>
                    <span className={`status-badge status-${request.status}`}>
                      {statusLabels[request.status]}
                    </span>
                  </div>
                  <p>服务项目 #{request.service_catalog_item_id}</p>
                  <footer>
                    <span>{formatDateTime(request.created_at)}</span>
                    <button
                      type="button"
                      className="text-button"
                      aria-label={`查看申请 #${request.id}`}
                      onClick={() => void showRequestDetail(request.id)}
                    >
                      查看详情
                    </button>
                  </footer>
                </article>
              ))}
            </div>
          )}
        </article>

        <article className="content-card request-detail-card">
          {isLoadingDetail ? (
            <p className="empty-state">正在加载申请详情…</p>
          ) : !selectedRequest ? (
            <p className="empty-state">选择一条申请查看详情和审计记录</p>
          ) : (
            <>
              <div className="request-detail-heading">
                <div>
                  <small>申请 #{selectedRequest.id}</small>
                  <h2>{selectedRequest.title}</h2>
                </div>
                <span
                  className={`status-badge status-${selectedRequest.status}`}
                >
                  {statusLabels[selectedRequest.status]}
                </span>
              </div>

              <dl className="request-metadata">
                <div>
                  <dt>服务项目</dt>
                  <dd>服务项目 #{selectedRequest.service_catalog_item_id}</dd>
                </div>
                <div>
                  <dt>申请人</dt>
                  <dd>用户 #{selectedRequest.requester_user_id}</dd>
                </div>
                <div>
                  <dt>提交时间</dt>
                  <dd>{formatDateTime(selectedRequest.created_at)}</dd>
                </div>
                <div>
                  <dt>决定时间</dt>
                  <dd>{formatDateTime(selectedRequest.decided_at)}</dd>
                </div>
              </dl>

              <section className="request-description">
                <h3>申请说明</h3>
                <p>{selectedRequest.description}</p>
              </section>

              {selectedRequest.decision_reason && (
                <section className="request-decision-reason">
                  <h3>审批说明</h3>
                  <p>{selectedRequest.decision_reason}</p>
                  <small>
                    决定人 #{selectedRequest.decided_by_user_id ?? "—"}
                  </small>
                </section>
              )}

              <section className="request-audit-section">
                <h3>审计记录</h3>
                {events.length === 0 ? (
                  <p className="empty-state">暂无审计事件</p>
                ) : (
                  <ol className="request-timeline">
                    {events.map((event) => (
                      <li key={event.id}>
                        <div>
                          <strong>{actionLabels[event.action]}</strong>
                          <span>{formatDateTime(event.created_at)}</span>
                        </div>
                        <p>
                          {event.from_status
                            ? `${statusLabels[event.from_status]} → ${statusLabels[event.to_status]}`
                            : `状态 → ${statusLabels[event.to_status]}`}
                        </p>
                        <small>操作者 #{event.actor_user_id}</small>
                        {event.reason && <blockquote>{event.reason}</blockquote>}
                      </li>
                    ))}
                  </ol>
                )}
              </section>
            </>
          )}
        </article>
      </div>
    </section>
  );
}
