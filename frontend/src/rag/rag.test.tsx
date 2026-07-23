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

function renderChatPage() {
  setAuthSession("rag-jwt");
  setActiveOrganizationId(1);
  return render(
    <MemoryRouter initialEntries={["/chat"]}>
      <App />
    </MemoryRouter>,
  );
}

const organization = {
  id: 1,
  name: "Platform Team",
  slug: "platform-team",
  role: "member",
  created_at: "2026-07-21T08:00:00Z",
};

const knowledgeBases = [
  {
    id: 101,
    organization_id: 1,
    created_by_user_id: 10,
    name: "IT Handbook",
    description: "IT support documentation",
    created_at: "2026-07-21T08:00:00Z",
    updated_at: "2026-07-21T08:00:00Z",
  },
  {
    id: 102,
    organization_id: 1,
    created_by_user_id: 10,
    name: "HR Handbook",
    description: "HR documentation",
    created_at: "2026-07-21T08:00:00Z",
    updated_at: "2026-07-21T08:00:00Z",
  },
];

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("enterprise RAG chat", () => {
  it("asks the selected knowledge base and renders grounded sources", async () => {
    const fetchMock = vi.fn((input: string, options?: RequestInit) => {
      const method = options?.method || "GET";
      if (input.endsWith("/users/me")) {
        return Promise.resolve(jsonResponse({ id: 20, username: "reader" }));
      }
      if (input.endsWith("/organizations")) {
        return Promise.resolve(jsonResponse({ organizations: [organization] }));
      }
      if (input.endsWith("/knowledge-bases")) {
        return Promise.resolve(jsonResponse({ knowledge_bases: knowledgeBases }));
      }
      if (
        input.endsWith("/rag/knowledge-bases/101/ask") &&
        method === "POST"
      ) {
        return Promise.resolve(
          jsonResponse({
            answer: "请在 IT 服务台提交 VPN 访问申请。[S1]",
            sources: [
              {
                reference: "[S1]",
                document_id: 301,
                chunk_id: 901,
                chunk_index: 2,
                score: 0.91,
                semantic_score: 0.88,
                lexical_score: 0.75,
                preview: "VPN 访问需要通过 IT 服务台提交申请并由负责人审批。",
              },
            ],
            rag_query_log_id: 701,
            retrieval: {
              top_score: 0.91,
              min_score: 0.5,
              matched_count: 1,
            },
          }),
        );
      }
      throw new Error(`unexpected request: ${input}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    renderChatPage();

    const questionInput = await screen.findByLabelText("输入问题");
    fireEvent.change(questionInput, {
      target: { value: "如何申请 VPN？" },
    });
    await waitFor(() => {
      expect(screen.getByRole("button", { name: "发送问题" })).toBeEnabled();
    });
    fireEvent.click(screen.getByRole("button", { name: "发送问题" }));

    expect(await screen.findByText("如何申请 VPN？")).toBeInTheDocument();
    expect(
      await screen.findByText("请在 IT 服务台提交 VPN 访问申请。[S1]"),
    ).toBeInTheDocument();
    expect(
      screen.getByText("VPN 访问需要通过 IT 服务台提交申请并由负责人审批。"),
    ).toBeInTheDocument();
    expect(screen.getByText("文档 #301 · 分块 #3")).toBeInTheDocument();

    const askCall = fetchMock.mock.calls.find(
      ([url]) =>
        typeof url === "string" &&
        url.endsWith("/rag/knowledge-bases/101/ask"),
    );
    expect(new Headers(askCall?.[1]?.headers).get("X-Organization-ID")).toBe(
      "1",
    );
    expect(JSON.parse(String(askCall?.[1]?.body))).toEqual({
      question: "如何申请 VPN？",
    });
  });

  it("shows a clear refusal when the knowledge base has no grounded result", async () => {
    const fetchMock = vi.fn((input: string, options?: RequestInit) => {
      if (input.endsWith("/users/me")) {
        return Promise.resolve(jsonResponse({ id: 20, username: "reader" }));
      }
      if (input.endsWith("/organizations")) {
        return Promise.resolve(jsonResponse({ organizations: [organization] }));
      }
      if (input.endsWith("/knowledge-bases")) {
        return Promise.resolve(
          jsonResponse({ knowledge_bases: [knowledgeBases[0]] }),
        );
      }
      if (
        input.endsWith("/rag/knowledge-bases/101/ask") &&
        options?.method === "POST"
      ) {
        return Promise.resolve(
          jsonResponse({
            answer: "资料库中没有足够相关的内容，暂时无法回答这个问题。",
            sources: [],
            rag_query_log_id: 702,
            retrieval: {
              top_score: null,
              min_score: 0.5,
              matched_count: 0,
            },
          }),
        );
      }
      throw new Error(`unexpected request: ${input}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    renderChatPage();

    const questionInput = await screen.findByLabelText("输入问题");
    fireEvent.change(questionInput, { target: { value: "明年的奖金是多少？" } });
    await waitFor(() => {
      expect(screen.getByRole("button", { name: "发送问题" })).toBeEnabled();
    });
    fireEvent.submit(questionInput.closest("form") as HTMLFormElement);

    expect(
      await screen.findByText(
        "资料库中没有足够相关的内容，暂时无法回答这个问题。",
      ),
    ).toBeInTheDocument();
    expect(screen.getByText("资料不足，未调用大模型生成答案")).toBeInTheDocument();
    expect(screen.queryByText("引用来源")).not.toBeInTheDocument();
  });

  it("clears the conversation when switching knowledge bases", async () => {
    const fetchMock = vi.fn((input: string, options?: RequestInit) => {
      if (input.endsWith("/users/me")) {
        return Promise.resolve(jsonResponse({ id: 20, username: "reader" }));
      }
      if (input.endsWith("/organizations")) {
        return Promise.resolve(jsonResponse({ organizations: [organization] }));
      }
      if (input.endsWith("/knowledge-bases")) {
        return Promise.resolve(jsonResponse({ knowledge_bases: knowledgeBases }));
      }
      if (input.endsWith("/rag/knowledge-bases/101/ask")) {
        return Promise.resolve(
          jsonResponse({
            answer: "IT 知识库回答",
            sources: [],
            rag_query_log_id: 703,
            retrieval: { top_score: null, min_score: 0.5, matched_count: 0 },
          }),
        );
      }
      throw new Error(`unexpected request: ${input} ${options?.method || "GET"}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    renderChatPage();

    const questionInput = await screen.findByLabelText("输入问题");
    fireEvent.change(questionInput, { target: { value: "测试问题" } });
    fireEvent.submit(questionInput.closest("form") as HTMLFormElement);
    expect(await screen.findByText("IT 知识库回答")).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("问答知识库"), {
      target: { value: "102" },
    });
    await waitFor(() => {
      expect(screen.queryByText("IT 知识库回答")).not.toBeInTheDocument();
    });
    expect(screen.getByText("向 HR Handbook 提问")).toBeInTheDocument();
  });
});
