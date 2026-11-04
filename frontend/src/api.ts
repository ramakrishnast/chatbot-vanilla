import type { ConversationDetail, ConversationSummary, ModelList, StreamEvent } from "./types";

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    message: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

const JSON_HEADERS = { "Content-Type": "application/json" };

async function errorDetail(response: Response): Promise<string> {
  try {
    const body = (await response.json()) as { detail?: unknown };
    if (typeof body.detail === "string") return body.detail;
    if (body.detail !== undefined) return JSON.stringify(body.detail);
  } catch {
    // not JSON; fall through
  }
  return `${response.status} ${response.statusText}`.trim();
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, { ...init, headers: { ...JSON_HEADERS, ...init?.headers } });
  if (!response.ok) throw new ApiError(response.status, await errorDetail(response));
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

export const api = {
  models: (refresh = false) => request<ModelList>(`/api/models${refresh ? "?refresh=true" : ""}`),
  conversations: () => request<ConversationSummary[]>("/api/conversations"),
  conversation: (id: string) => request<ConversationDetail>(`/api/conversations/${id}`),
  createConversation: (model: string | null) =>
    request<ConversationSummary>("/api/conversations", {
      method: "POST",
      body: JSON.stringify({ model }),
    }),
  updateConversation: (id: string, changes: { title?: string; model?: string }) =>
    request<ConversationSummary>(`/api/conversations/${id}`, {
      method: "PATCH",
      body: JSON.stringify(changes),
    }),
  deleteConversation: (id: string) =>
    request<void>(`/api/conversations/${id}`, { method: "DELETE" }),
};

/** Parse a stream of newline-delimited JSON, tolerating lines split across chunks. */
export async function* parseNdjson(
  stream: ReadableStream<Uint8Array>,
): AsyncGenerator<StreamEvent> {
  const reader = stream.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  try {
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      let newline = buffer.indexOf("\n");
      while (newline >= 0) {
        const line = buffer.slice(0, newline).trim();
        buffer = buffer.slice(newline + 1);
        if (line) yield JSON.parse(line) as StreamEvent;
        newline = buffer.indexOf("\n");
      }
    }
    const rest = (buffer + decoder.decode()).trim();
    if (rest) yield JSON.parse(rest) as StreamEvent;
  } finally {
    reader.releaseLock();
  }
}

export interface StreamRequest {
  method: "POST" | "PUT";
  path: string;
  body: unknown;
  signal: AbortSignal;
}

/** Call a streaming endpoint and hand each event to `onEvent`. Aborting `signal` stops it. */
export async function streamChat(
  { method, path, body, signal }: StreamRequest,
  onEvent: (event: StreamEvent) => void,
): Promise<void> {
  const response = await fetch(path, {
    method,
    headers: JSON_HEADERS,
    body: JSON.stringify(body),
    signal,
  });
  if (!response.ok || !response.body) {
    throw new ApiError(response.status, await errorDetail(response));
  }
  for await (const event of parseNdjson(response.body)) onEvent(event);
}
