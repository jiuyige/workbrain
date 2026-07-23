import { type FormEvent, useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";

import { getApiErrorMessage } from "../api/errorMessage";
import { useOrganization } from "../organization/OrganizationContext";
import {
  createServiceCatalogItem,
  listServiceCatalogItems,
  setServiceCatalogItemActive,
  type ServiceCatalogItem,
} from "../serviceCatalog/api";
import {
  createServiceRequest,
  type ServiceRequest,
} from "../serviceRequest/api";

export function ServiceCatalogPage() {
  const { activeOrganization } = useOrganization();
  const [items, setItems] = useState<ServiceCatalogItem[]>([]);
  const [selectedItemId, setSelectedItemId] = useState<number | null>(null);
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [catalogName, setCatalogName] = useState("");
  const [catalogDescription, setCatalogDescription] = useState("");
  const [createdRequest, setCreatedRequest] =
    useState<ServiceRequest | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [isManagingCatalog, setIsManagingCatalog] = useState(false);
  const [errorMessage, setErrorMessage] = useState("");
  const activeOrganizationIdRef = useRef<number | null>(null);

  useEffect(() => {
    const organizationId = activeOrganization?.id ?? null;
    activeOrganizationIdRef.current = organizationId;
    setItems([]);
    setSelectedItemId(null);
    setTitle("");
    setDescription("");
    setCatalogName("");
    setCatalogDescription("");
    setCreatedRequest(null);
    setErrorMessage("");

    if (organizationId === null) {
      return;
    }

    let isActive = true;
    setIsLoading(true);
    listServiceCatalogItems(activeOrganization?.role === "admin")
      .then((catalogItems) => {
        if (isActive) {
          setItems(catalogItems);
          setSelectedItemId(
            catalogItems.find((item) => item.is_active)?.id ?? null,
          );
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
  }, [activeOrganization?.id, activeOrganization?.role]);

  const activeItems = items.filter((item) => item.is_active);

  async function handleCreateCatalogItem(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const normalizedName = catalogName.trim();
    const normalizedDescription = catalogDescription.trim();
    if (!activeOrganization || !normalizedName) {
      return;
    }

    const submittedOrganizationId = activeOrganization.id;
    setErrorMessage("");
    setIsManagingCatalog(true);
    try {
      const item = await createServiceCatalogItem(
        normalizedName,
        normalizedDescription,
      );
      if (activeOrganizationIdRef.current !== submittedOrganizationId) {
        return;
      }
      setItems((currentItems) => [...currentItems, item]);
      setSelectedItemId((currentId) => currentId ?? item.id);
      setCatalogName("");
      setCatalogDescription("");
    } catch (error) {
      if (activeOrganizationIdRef.current === submittedOrganizationId) {
        setErrorMessage(getApiErrorMessage(error));
      }
    } finally {
      if (activeOrganizationIdRef.current === submittedOrganizationId) {
        setIsManagingCatalog(false);
      }
    }
  }

  async function handleToggleCatalogItem(item: ServiceCatalogItem) {
    if (!activeOrganization) {
      return;
    }

    const submittedOrganizationId = activeOrganization.id;
    setErrorMessage("");
    setIsManagingCatalog(true);
    try {
      const updatedItem = await setServiceCatalogItemActive(
        item.id,
        !item.is_active,
      );
      if (activeOrganizationIdRef.current !== submittedOrganizationId) {
        return;
      }
      setItems((currentItems) =>
        currentItems.map((currentItem) =>
          currentItem.id === updatedItem.id ? updatedItem : currentItem,
        ),
      );
      if (updatedItem.is_active && selectedItemId === null) {
        setSelectedItemId(updatedItem.id);
      } else if (!updatedItem.is_active && selectedItemId === updatedItem.id) {
        const nextItem = items.find(
          (currentItem) =>
            currentItem.id !== updatedItem.id && currentItem.is_active,
        );
        setSelectedItemId(nextItem?.id ?? null);
      }
    } catch (error) {
      if (activeOrganizationIdRef.current === submittedOrganizationId) {
        setErrorMessage(getApiErrorMessage(error));
      }
    } finally {
      if (activeOrganizationIdRef.current === submittedOrganizationId) {
        setIsManagingCatalog(false);
      }
    }
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const normalizedTitle = title.trim();
    const normalizedDescription = description.trim();
    if (
      selectedItemId === null ||
      !normalizedTitle ||
      !normalizedDescription ||
      !activeOrganization
    ) {
      return;
    }

    const submittedOrganizationId = activeOrganization.id;
    setErrorMessage("");
    setCreatedRequest(null);
    setIsSubmitting(true);
    try {
      const request = await createServiceRequest(
        selectedItemId,
        normalizedTitle,
        normalizedDescription,
      );
      if (activeOrganizationIdRef.current !== submittedOrganizationId) {
        return;
      }
      setCreatedRequest(request);
      setTitle("");
      setDescription("");
    } catch (error) {
      if (activeOrganizationIdRef.current === submittedOrganizationId) {
        setErrorMessage(getApiErrorMessage(error));
      }
    } finally {
      if (activeOrganizationIdRef.current === submittedOrganizationId) {
        setIsSubmitting(false);
      }
    }
  }

  return (
    <section className="management-page service-catalog-page">
      <div className="page-heading">
        <p className="eyebrow">企业 IT 服务</p>
        <h1>IT 服务目录</h1>
        <p>选择当前组织提供的服务，填写业务需求后提交审批。</p>
      </div>

      {errorMessage && (
        <p className="form-message error" role="alert">
          {errorMessage}
        </p>
      )}

      {activeOrganization?.role === "admin" && (
        <article className="content-card">
          <div className="card-heading">
            <div>
              <h2>管理服务目录</h2>
              <p>创建服务项目，并控制它是否可被组织成员申请。</p>
            </div>
          </div>
          <form className="stack-form" onSubmit={handleCreateCatalogItem}>
            <label>
              服务名称
              <input
                value={catalogName}
                onChange={(event) => setCatalogName(event.target.value)}
                maxLength={100}
                placeholder="例如：VPN 权限"
                required
                disabled={isManagingCatalog}
              />
            </label>
            <label>
              服务说明
              <textarea
                value={catalogDescription}
                onChange={(event) =>
                  setCatalogDescription(event.target.value)
                }
                maxLength={1000}
                rows={3}
                placeholder="说明该服务的用途和申请范围"
                disabled={isManagingCatalog}
              />
            </label>
            <button
              type="submit"
              disabled={!catalogName.trim() || isManagingCatalog}
            >
              {isManagingCatalog ? "正在处理…" : "创建服务项目"}
            </button>
          </form>

          {items.length > 0 && (
            <div className="service-catalog-grid">
              {items.map((item) => (
                <article className="service-catalog-card" key={item.id}>
                  <div>
                    <span className="role-badge">
                      {item.is_active ? "已启用" : "已停用"}
                    </span>
                    <h3>{item.name}</h3>
                    <p>{item.description || "暂无服务说明"}</p>
                  </div>
                  <button
                    type="button"
                    aria-label={`${item.is_active ? "停用" : "启用"} ${item.name}`}
                    onClick={() => void handleToggleCatalogItem(item)}
                    disabled={isManagingCatalog}
                  >
                    {item.is_active ? "停用" : "重新启用"}
                  </button>
                </article>
              ))}
            </div>
          )}
        </article>
      )}

      <article className="content-card">
        <div className="card-heading">
          <div>
            <h2>可申请服务</h2>
            <p>这里只显示当前仍处于启用状态的服务项目。</p>
          </div>
          {activeItems.length > 0 && (
            <span className="catalog-count">{activeItems.length} 项服务</span>
          )}
        </div>

        {isLoading ? (
          <p className="empty-state">正在加载服务目录…</p>
        ) : activeItems.length === 0 ? (
          <p className="empty-state">当前组织没有可申请的 IT 服务</p>
        ) : (
          <div className="service-catalog-grid">
            {activeItems.map((item) => (
              <article
                className={
                  selectedItemId === item.id
                    ? "service-catalog-card selected"
                    : "service-catalog-card"
                }
                key={item.id}
              >
                <div>
                  <span className="role-badge">可申请</span>
                  <h3>{item.name}</h3>
                  <p>{item.description || "暂无服务说明"}</p>
                </div>
                <button
                  type="button"
                  aria-label={`申请 ${item.name}`}
                  onClick={() => {
                    setSelectedItemId(item.id);
                    setCreatedRequest(null);
                  }}
                >
                  {selectedItemId === item.id ? "已选择" : "选择服务"}
                </button>
              </article>
            ))}
          </div>
        )}
      </article>

      {activeItems.length > 0 && selectedItemId !== null && (
        <article className="content-card service-request-form-card">
          <div className="card-heading">
            <div>
              <h2>提交服务申请</h2>
              <p>申请提交后进入待审批状态，请完整说明使用场景和原因。</p>
            </div>
          </div>
          <form className="stack-form service-request-form" onSubmit={handleSubmit}>
            <label>
              服务项目
              <select
                value={selectedItemId}
                onChange={(event) => {
                  setSelectedItemId(Number(event.target.value));
                  setCreatedRequest(null);
                }}
                disabled={isSubmitting}
              >
                {activeItems.map((item) => (
                  <option key={item.id} value={item.id}>
                    {item.name} · #{item.id}
                  </option>
                ))}
              </select>
            </label>
            <label>
              申请标题
              <input
                value={title}
                onChange={(event) => setTitle(event.target.value)}
                maxLength={200}
                placeholder="例如：远程办公 VPN 权限"
                required
                disabled={isSubmitting}
              />
            </label>
            <label>
              申请说明
              <textarea
                value={description}
                onChange={(event) => setDescription(event.target.value)}
                maxLength={2000}
                rows={5}
                placeholder="说明使用场景、业务原因和必要信息"
                required
                disabled={isSubmitting}
              />
            </label>
            <button
              type="submit"
              disabled={!title.trim() || !description.trim() || isSubmitting}
            >
              {isSubmitting ? "正在提交…" : "提交申请"}
            </button>
          </form>

          {createdRequest && (
            <div className="service-request-success" role="status">
              <div>
                <strong>申请 #{createdRequest.id} 已提交</strong>
                <span className="status-badge status-ready">待审批</span>
              </div>
              <p>{createdRequest.title}</p>
              <Link to="/service-requests">查看我的申请</Link>
            </div>
          )}
        </article>
      )}
    </section>
  );
}
