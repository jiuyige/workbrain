import { type FormEvent, useEffect, useState } from "react";

import { getApiErrorMessage } from "../api/errorMessage";
import { useAuth } from "../auth/AuthContext";
import {
  createOrganization,
  disableOrganizationMember,
  inviteOrganizationMember,
  listOrganizationMembers,
  type OrganizationMember,
  type OrganizationRole,
} from "../organization/api";
import { useOrganization } from "../organization/OrganizationContext";

const roleLabels: Record<OrganizationRole, string> = {
  member: "成员",
  approver: "审批人",
  admin: "管理员",
};

export function OrganizationPage() {
  const { currentUser } = useAuth();
  const {
    organizations,
    activeOrganization,
    isLoading: isOrganizationLoading,
    errorMessage: organizationError,
    refreshOrganizations,
    selectOrganization,
  } = useOrganization();
  const [members, setMembers] = useState<OrganizationMember[]>([]);
  const [isMembersLoading, setIsMembersLoading] = useState(false);
  const [pageError, setPageError] = useState("");
  const [organizationName, setOrganizationName] = useState("");
  const [organizationSlug, setOrganizationSlug] = useState("");
  const [memberUsername, setMemberUsername] = useState("");
  const [memberRole, setMemberRole] =
    useState<OrganizationRole>("member");
  const [isSubmitting, setIsSubmitting] = useState(false);

  useEffect(() => {
    setMembers([]);
    setPageError("");
    if (!activeOrganization || activeOrganization.role !== "admin") {
      return;
    }

    let isActive = true;
    setIsMembersLoading(true);
    listOrganizationMembers()
      .then((items) => {
        if (isActive) {
          setMembers(items);
        }
      })
      .catch((error) => {
        if (isActive) {
          setPageError(getApiErrorMessage(error));
        }
      })
      .finally(() => {
        if (isActive) {
          setIsMembersLoading(false);
        }
      });

    return () => {
      isActive = false;
    };
  }, [activeOrganization?.id, activeOrganization?.role]);

  async function handleCreateOrganization(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setPageError("");
    setIsSubmitting(true);
    try {
      const created = await createOrganization(
        organizationName.trim(),
        organizationSlug.trim(),
      );
      setOrganizationName("");
      setOrganizationSlug("");
      await refreshOrganizations(created.id);
    } catch (error) {
      setPageError(getApiErrorMessage(error));
    } finally {
      setIsSubmitting(false);
    }
  }

  async function handleInviteMember(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setPageError("");
    setIsSubmitting(true);
    try {
      const member = await inviteOrganizationMember(
        memberUsername.trim(),
        memberRole,
      );
      setMembers((current) => [...current, member]);
      setMemberUsername("");
      setMemberRole("member");
    } catch (error) {
      setPageError(getApiErrorMessage(error));
    } finally {
      setIsSubmitting(false);
    }
  }

  async function handleDisableMember(member: OrganizationMember) {
    setPageError("");
    try {
      const disabled = await disableOrganizationMember(member.id);
      setMembers((current) =>
        current.map((item) => (item.id === disabled.id ? disabled : item)),
      );
    } catch (error) {
      setPageError(getApiErrorMessage(error));
    }
  }

  return (
    <section className="management-page">
      <div className="page-heading">
        <p className="eyebrow">组织上下文</p>
        <h1>组织与成员</h1>
        <p>切换工作空间，创建组织并管理成员角色。</p>
      </div>

      {(pageError || organizationError) && (
        <p className="form-message error" role="alert">
          {pageError || organizationError}
        </p>
      )}

      <div className="content-grid two-columns">
        <article className="content-card">
          <div className="card-heading">
            <div>
              <h2>我的组织</h2>
              <p>你只能切换到有效成员关系对应的组织。</p>
            </div>
          </div>
          {isOrganizationLoading ? (
            <p className="empty-state">正在加载组织…</p>
          ) : (
            <div className="organization-list">
              {organizations.map((organization) => (
                <button
                  type="button"
                  key={organization.id}
                  className={
                    organization.id === activeOrganization?.id
                      ? "organization-item active"
                      : "organization-item"
                  }
                  onClick={() => selectOrganization(organization.id)}
                >
                  <span>
                    <strong>{organization.name}</strong>
                    <small>{organization.slug}</small>
                  </span>
                  <span className="role-badge">
                    {roleLabels[organization.role]}
                  </span>
                </button>
              ))}
            </div>
          )}
        </article>

        <article className="content-card">
          <div className="card-heading">
            <div>
              <h2>创建组织</h2>
              <p>创建后你会自动成为该组织管理员。</p>
            </div>
          </div>
          <form className="stack-form" onSubmit={handleCreateOrganization}>
            <label>
              组织名称
              <input
                value={organizationName}
                onChange={(event) => setOrganizationName(event.target.value)}
                maxLength={100}
                required
                disabled={isSubmitting}
              />
            </label>
            <label>
              组织标识
              <input
                value={organizationSlug}
                onChange={(event) => setOrganizationSlug(event.target.value)}
                pattern="[a-z0-9]+(?:-[a-z0-9]+)*"
                minLength={3}
                maxLength={63}
                placeholder="例如 platform-team"
                required
                disabled={isSubmitting}
              />
            </label>
            <button type="submit" disabled={isSubmitting}>
              创建组织
            </button>
          </form>
        </article>
      </div>

      <article className="content-card members-card">
        <div className="card-heading">
          <div>
            <h2>组织成员</h2>
            <p>{activeOrganization?.name || "请先选择组织"}</p>
          </div>
        </div>
        {activeOrganization?.role !== "admin" ? (
          <p className="empty-state">只有组织管理员可以管理成员。</p>
        ) : (
          <>
            <form className="inline-form" onSubmit={handleInviteMember}>
              <label>
                成员用户名
                <input
                  value={memberUsername}
                  onChange={(event) => setMemberUsername(event.target.value)}
                  required
                  disabled={isSubmitting}
                />
              </label>
              <label>
                成员角色
                <select
                  value={memberRole}
                  onChange={(event) =>
                    setMemberRole(event.target.value as OrganizationRole)
                  }
                  disabled={isSubmitting}
                >
                  <option value="member">成员</option>
                  <option value="approver">审批人</option>
                  <option value="admin">管理员</option>
                </select>
              </label>
              <button type="submit" disabled={isSubmitting}>
                添加成员
              </button>
            </form>
            {isMembersLoading ? (
              <p className="empty-state">正在加载成员…</p>
            ) : (
              <div className="data-table-wrapper">
                <table className="data-table">
                  <thead>
                    <tr>
                      <th>用户名</th>
                      <th>角色</th>
                      <th>状态</th>
                      <th>操作</th>
                    </tr>
                  </thead>
                  <tbody>
                    {members.map((member) => (
                      <tr key={member.id}>
                        <td>{member.username}</td>
                        <td>{roleLabels[member.role]}</td>
                        <td>{member.is_active ? "正常" : "已停用"}</td>
                        <td>
                          {member.is_active &&
                          member.user_id !== currentUser?.id ? (
                            <button
                              type="button"
                              className="text-button danger"
                              aria-label={`停用成员 ${member.username}`}
                              onClick={() => void handleDisableMember(member)}
                            >
                              停用
                            </button>
                          ) : (
                            "—"
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </>
        )}
      </article>
    </section>
  );
}
