import { useOrganization } from "./OrganizationContext";

export function OrganizationSelector() {
  const {
    organizations,
    activeOrganization,
    isLoading,
    selectOrganization,
  } = useOrganization();

  if (isLoading) {
    return <span className="organization-loading">正在加载组织…</span>;
  }
  if (!activeOrganization) {
    return <span className="organization-loading">暂无可用组织</span>;
  }

  return (
    <label className="organization-selector">
      <span>当前组织</span>
      <select
        value={activeOrganization.id}
        onChange={(event) => selectOrganization(Number(event.target.value))}
      >
        {organizations.map((organization) => (
          <option key={organization.id} value={organization.id}>
            {organization.name} · {organization.role}
          </option>
        ))}
      </select>
    </label>
  );
}
