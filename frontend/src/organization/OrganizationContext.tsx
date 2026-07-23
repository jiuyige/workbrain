import {
  createContext,
  type ReactNode,
  useContext,
  useEffect,
  useState,
} from "react";

import { getApiErrorMessage } from "../api/errorMessage";
import { useAuth } from "../auth/AuthContext";
import {
  getActiveOrganizationId,
  setActiveOrganizationId,
} from "../auth/session";
import { listOrganizations, type Organization } from "./api";

interface OrganizationContextValue {
  organizations: Organization[];
  activeOrganization: Organization | null;
  isLoading: boolean;
  errorMessage: string;
  selectOrganization: (organizationId: number) => void;
  refreshOrganizations: (preferredOrganizationId?: number) => Promise<void>;
}

const OrganizationContext = createContext<OrganizationContextValue | null>(null);

export function OrganizationProvider({ children }: { children: ReactNode }) {
  const { currentUser } = useAuth();
  const [organizations, setOrganizations] = useState<Organization[]>([]);
  const [activeOrganization, setActiveOrganization] =
    useState<Organization | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [errorMessage, setErrorMessage] = useState("");

  async function refreshOrganizations(
    preferredOrganizationId?: number,
  ): Promise<void> {
    setIsLoading(true);
    setErrorMessage("");
    try {
      const availableOrganizations = await listOrganizations();
      const requestedId =
        preferredOrganizationId ?? getActiveOrganizationId() ?? undefined;
      const selected =
        availableOrganizations.find((item) => item.id === requestedId) ??
        availableOrganizations[0] ??
        null;

      setOrganizations(availableOrganizations);
      setActiveOrganization(selected);
      if (selected) {
        setActiveOrganizationId(selected.id);
      }
    } catch (error) {
      setOrganizations([]);
      setActiveOrganization(null);
      setErrorMessage(getApiErrorMessage(error));
    } finally {
      setIsLoading(false);
    }
  }

  useEffect(() => {
    if (!currentUser) {
      setOrganizations([]);
      setActiveOrganization(null);
      setErrorMessage("");
      setIsLoading(false);
      return;
    }

    void refreshOrganizations();
  }, [currentUser]);

  function selectOrganization(organizationId: number): void {
    const selected = organizations.find((item) => item.id === organizationId);
    if (!selected) {
      return;
    }
    setActiveOrganizationId(selected.id);
    setActiveOrganization(selected);
  }

  return (
    <OrganizationContext.Provider
      value={{
        organizations,
        activeOrganization,
        isLoading,
        errorMessage,
        selectOrganization,
        refreshOrganizations,
      }}
    >
      {children}
    </OrganizationContext.Provider>
  );
}

export function useOrganization(): OrganizationContextValue {
  const context = useContext(OrganizationContext);
  if (!context) {
    throw new Error("useOrganization must be used inside OrganizationProvider");
  }
  return context;
}
