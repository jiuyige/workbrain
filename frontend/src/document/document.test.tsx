import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, vi } from "vitest";

import App from "../App";
import { setActiveOrganizationId, setAuthSession } from "../auth/session";

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function renderDocumentsPage() {
  setAuthSession("document-jwt");
  setActiveOrganizationId(1);
  return render(
    <MemoryRouter initialEntries={["/documents"]}>
      <App />
    </MemoryRouter>,
  );
}

const organization = {
  id: 1,
  name: "Platform Team",
  slug: "platform-team",
  role: "admin",
  created_at: "2026-07-21T08:00:00Z",
};

const knowledgeBase = {
  id: 101,
  organization_id: 1,
  created_by_user_id: 10,
  name: "Platform Docs",
  description: "Team documentation",
  created_at: "2026-07-21T08:00:00Z",
  updated_at: "2026-07-21T08:00:00Z",
};

const readyDocument = {
  id: 301,
  owner_id: 10,
  organization_id: 1,
  knowledge_base_id: 101,
  filename: "vpn-guide.md",
  content_type: "text/markdown",
  version: 1,
  status: "ready",
  chunk_count: 2,
  embedded_chunk_count: 2,
  published_chunk_count: 0,
  is_ready_for_publish: true,
  is_ready_for_rag: false,
};

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("document management", () => {
  it("uploads a document, follows its job and reloads the processed result", async () => {
    let documentListCalls = 0;
    const fetchMock = vi.fn((input: string, options?: RequestInit) => {
      const method = options?.method || "GET";
      if (input.endsWith("/users/me")) {
        return Promise.resolve(jsonResponse({ id: 10, username: "admin" }));
      }
      if (input.endsWith("/organizations")) {
        return Promise.resolve(jsonResponse({ organizations: [organization] }));
      }
      if (input.endsWith("/knowledge-bases")) {
        return Promise.resolve(
          jsonResponse({ knowledge_bases: [knowledgeBase] }),
        );
      }
      if (
        input.endsWith("/knowledge-bases/101/documents") &&
        method === "GET"
      ) {
        documentListCalls += 1;
        return Promise.resolve(
          jsonResponse({
            knowledge_base_id: 101,
            documents: documentListCalls === 1 ? [] : [readyDocument],
          }),
        );
      }
      if (
        input.endsWith("/knowledge-bases/101/documents") &&
        method === "POST"
      ) {
        expect(options?.body).toBeInstanceOf(FormData);
        expect(new Headers(options?.headers).has("Content-Type")).toBe(false);
        return Promise.resolve(
          jsonResponse(
            {
              message: "upload success",
              document: {
                id: 301,
                owner_id: 10,
                organization_id: 1,
                knowledge_base_id: 101,
                filename: "vpn-guide.md",
                content_type: "text/markdown",
                version: 1,
                status: "uploaded",
              },
              job: { id: 501, status: "queued" },
            },
            202,
          ),
        );
      }
      if (input.endsWith("/jobs/501")) {
        return Promise.resolve(
          jsonResponse({
            id: 501,
            created_by_user_id: 10,
            job_type: "document_processing",
            status: "succeeded",
            error_message: null,
            attempt_count: 1,
            next_retry_at: null,
            created_at: "2026-07-21T08:00:00Z",
            started_at: "2026-07-21T08:00:01Z",
            finished_at: "2026-07-21T08:00:02Z",
          }),
        );
      }
      throw new Error(`unexpected request: ${input}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    renderDocumentsPage();

    const fileInput = await screen.findByLabelText("选择文档");
    const file = new File(["# VPN\nConnect safely."], "vpn-guide.md", {
      type: "text/markdown",
    });
    fireEvent.change(fileInput, { target: { files: [file] } });
    fireEvent.submit(fileInput.closest("form") as HTMLFormElement);

    expect(await screen.findByText("处理成功")).toBeInTheDocument();
    expect(await screen.findByText("vpn-guide.md")).toBeInTheDocument();
    await waitFor(() => expect(documentListCalls).toBe(2));

    const uploadCall = fetchMock.mock.calls.find(
      ([url, options]) =>
        typeof url === "string" &&
        url.endsWith("/knowledge-bases/101/documents") &&
        options?.method === "POST",
    );
    expect(new Headers(uploadCall?.[1]?.headers).get("X-Organization-ID")).toBe(
      "1",
    );
  });

  it("lets an approver publish, inspect and archive a document", async () => {
    const approverOrganization = { ...organization, role: "approver" };
    let currentDocument = readyDocument;
    const fetchMock = vi.fn((input: string, options?: RequestInit) => {
      const method = options?.method || "GET";
      if (input.endsWith("/users/me")) {
        return Promise.resolve(jsonResponse({ id: 11, username: "approver" }));
      }
      if (input.endsWith("/organizations")) {
        return Promise.resolve(
          jsonResponse({ organizations: [approverOrganization] }),
        );
      }
      if (input.endsWith("/knowledge-bases")) {
        return Promise.resolve(
          jsonResponse({ knowledge_bases: [knowledgeBase] }),
        );
      }
      if (
        input.endsWith("/knowledge-bases/101/documents") &&
        method === "GET"
      ) {
        return Promise.resolve(
          jsonResponse({ knowledge_base_id: 101, documents: [currentDocument] }),
        );
      }
      if (input.endsWith("/documents/301/content")) {
        return Promise.resolve(
          jsonResponse({
            document: {
              ...readyDocument,
              content: "VPN setup instructions",
            },
          }),
        );
      }
      if (input.endsWith("/documents/301/chunks")) {
        return Promise.resolve(
          jsonResponse({
            document: {
              id: 301,
              filename: "vpn-guide.md",
              version: 1,
              status: "ready",
            },
            chunks: [
              {
                id: 901,
                chunk_index: 0,
                content: "VPN setup instructions",
                char_count: 22,
                document_version: 1,
                status: "ready",
              },
            ],
          }),
        );
      }
      if (input.endsWith("/documents/301/publish") && method === "POST") {
        currentDocument = {
          ...currentDocument,
          status: "published",
          published_chunk_count: 2,
          is_ready_for_publish: false,
          is_ready_for_rag: true,
        };
        return Promise.resolve(
          jsonResponse({
            message: "document published",
            document_id: 301,
            status: "published",
            published_chunk_count: 2,
          }),
        );
      }
      if (input.endsWith("/documents/301/archive") && method === "POST") {
        currentDocument = {
          ...currentDocument,
          status: "archived",
          published_chunk_count: 0,
          is_ready_for_rag: false,
        };
        return Promise.resolve(
          jsonResponse({
            message: "document archived",
            document_id: 301,
            status: "archived",
            archived_chunk_count: 2,
          }),
        );
      }
      throw new Error(`unexpected request: ${input}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    renderDocumentsPage();

    expect(await screen.findByText("vpn-guide.md")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "查看正文" }));
    expect(await screen.findByText("VPN setup instructions")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "查看分块" }));
    expect(await screen.findByText("分块 #1 · 22 字符")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "发布" }));
    expect(await screen.findByText("可用于 RAG")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "归档" }));
    expect(await screen.findByText("已归档")).toBeInTheDocument();
  });

  it("keeps publish and archive actions hidden from ordinary members", async () => {
    const memberOrganization = { ...organization, role: "member" };
    const fetchMock = vi.fn((input: string) => {
      if (input.endsWith("/users/me")) {
        return Promise.resolve(jsonResponse({ id: 20, username: "reader" }));
      }
      if (input.endsWith("/organizations")) {
        return Promise.resolve(
          jsonResponse({ organizations: [memberOrganization] }),
        );
      }
      if (input.endsWith("/knowledge-bases")) {
        return Promise.resolve(
          jsonResponse({ knowledge_bases: [knowledgeBase] }),
        );
      }
      if (input.endsWith("/knowledge-bases/101/documents")) {
        return Promise.resolve(
          jsonResponse({ knowledge_base_id: 101, documents: [readyDocument] }),
        );
      }
      throw new Error(`unexpected request: ${input}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    renderDocumentsPage();

    expect(await screen.findByText("vpn-guide.md")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "上传并处理" }),
    ).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "发布" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "归档" })).not.toBeInTheDocument();
  });
});
