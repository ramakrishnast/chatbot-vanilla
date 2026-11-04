import { useCallback, useEffect, useRef, useState } from "react";

import { api, streamChat, type StreamRequest } from "./api";
import type { ConversationSummary, Message, ModelInfo } from "./types";

const PENDING_USER = "pending-user";
const PENDING_REPLY = "pending-reply";
const MODEL_KEY = "chat.model";

function errorText(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

function idFromUrl(): string | null {
  const match = /^#\/c\/([0-9a-f-]{36})$/i.exec(window.location.hash);
  return match?.[1] ?? null;
}

function storedModel(): string | null {
  try {
    return localStorage.getItem(MODEL_KEY);
  } catch {
    return null;
  }
}

function rememberModel(name: string): void {
  try {
    localStorage.setItem(MODEL_KEY, name);
  } catch {
    // private mode or storage disabled: the choice just isn't remembered
  }
}

function placeholder(id: string, role: Message["role"], content = "", model: string | null = null) {
  const message: Message = {
    id,
    position: Number.MAX_SAFE_INTEGER,
    role,
    content,
    thinking: null,
    model,
    status: role === "assistant" ? "streaming" : "complete",
    created_at: new Date().toISOString(),
  };
  return message;
}

export function useChat() {
  const [conversations, setConversations] = useState<ConversationSummary[]>([]);
  const [activeId, setActiveId] = useState<string | null>(idFromUrl);
  const [messages, setMessages] = useState<Message[]>([]);
  const [models, setModels] = useState<ModelInfo[]>([]);
  const [model, setModel] = useState<string | null>(null);
  const [streaming, setStreaming] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const activeIdRef = useRef(activeId);
  const abortRef = useRef<AbortController | null>(null);
  const streamConversationRef = useRef<string | null>(null);
  const skipLoadRef = useRef<string | null>(null);

  const navigate = useCallback((id: string | null) => {
    const url = id ? `#/c/${id}` : window.location.pathname + window.location.search;
    window.history.pushState(null, "", url);
    activeIdRef.current = id;
    setActiveId(id);
  }, []);

  const refreshConversations = useCallback(async () => {
    try {
      setConversations(await api.conversations());
    } catch (e) {
      setError(`Could not load conversations: ${errorText(e)}`);
    }
  }, []);

  const loadModels = useCallback(async (refresh = false) => {
    try {
      const list = await api.models(refresh);
      setModels(list.models);
      const names = new Set(list.models.map((m) => m.name));
      setModel((current) => {
        if (current && names.has(current)) return current;
        const saved = storedModel();
        if (saved && names.has(saved)) return saved;
        return list.default;
      });
      if (list.models.length === 0) {
        setError("No chat models are installed in Ollama. Run `ollama pull <model>`, then reload.");
      }
    } catch (e) {
      setError(`Can't reach Ollama: ${errorText(e)}`);
    }
  }, []);

  useEffect(() => {
    void refreshConversations();
    void loadModels();
  }, [refreshConversations, loadModels]);

  // Back/forward buttons switch conversations; leaving a streaming chat stops its reply.
  useEffect(() => {
    const onPop = () => {
      const id = idFromUrl();
      if (id !== streamConversationRef.current) abortRef.current?.abort();
      activeIdRef.current = id;
      setActiveId(id);
    };
    window.addEventListener("popstate", onPop);
    return () => window.removeEventListener("popstate", onPop);
  }, []);

  useEffect(() => {
    if (!activeId) {
      setMessages([]);
      return;
    }
    if (skipLoadRef.current === activeId) {
      skipLoadRef.current = null; // just created here; messages are already in state
      return;
    }
    let cancelled = false;
    setLoading(true);
    api
      .conversation(activeId)
      .then((detail) => {
        if (cancelled) return;
        setMessages(detail.messages);
        if (detail.model) setModel(detail.model);
      })
      .catch((e: unknown) => {
        if (cancelled) return;
        setError(`Could not open conversation: ${errorText(e)}`);
        navigate(null);
      })
      .finally(() => !cancelled && setLoading(false));
    return () => {
      cancelled = true;
    };
  }, [activeId, navigate]);

  const runStream = useCallback(
    async (conversationId: string, request: Omit<StreamRequest, "signal">) => {
      const controller = new AbortController();
      abortRef.current = controller;
      streamConversationRef.current = conversationId;
      setStreaming(true);
      setError(null);

      const isCurrent = () => activeIdRef.current === conversationId;
      const patchReply = (patch: (m: Message) => Message) =>
        setMessages((all) => all.map((m) => (m.id === PENDING_REPLY ? patch(m) : m)));

      try {
        await streamChat({ ...request, signal: controller.signal }, (event) => {
          if (event.type === "user_message") {
            // The server has saved the message (and a placeholder title for a new chat).
            void refreshConversations();
          }
          if (event.type === "title") {
            setConversations((all) =>
              all.map((c) => (c.id === conversationId ? { ...c, title: event.title } : c)),
            );
            return;
          }
          if (!isCurrent()) return;
          switch (event.type) {
            case "user_message":
              setMessages((all) =>
                all.map((m) =>
                  m.id === PENDING_USER || m.id === event.message.id ? event.message : m,
                ),
              );
              break;
            case "thinking":
              patchReply((m) => ({ ...m, thinking: (m.thinking ?? "") + event.content }));
              break;
            case "delta":
              patchReply((m) => ({ ...m, content: m.content + event.content }));
              break;
            case "error":
              setError(event.detail);
              break;
            case "done": {
              const saved = event.message;
              patchReply((m) => saved ?? { ...m, status: "complete" });
              break;
            }
          }
        });
      } catch (e) {
        if (controller.signal.aborted) {
          patchReply((m) => ({ ...m, status: "stopped" }));
          // The server saves the partial reply; reload shortly to pick up its real id.
          window.setTimeout(() => {
            if (!isCurrent() || abortRef.current) return;
            void api.conversation(conversationId).then((detail) => {
              if (isCurrent() && !abortRef.current) setMessages(detail.messages);
            });
          }, 400);
        } else {
          setError(errorText(e));
          patchReply((m) => ({ ...m, status: "error" }));
        }
      } finally {
        if (abortRef.current === controller) {
          abortRef.current = null;
          streamConversationRef.current = null;
          setStreaming(false);
        }
        void refreshConversations();
      }
    },
    [refreshConversations],
  );

  const send = useCallback(
    async (text: string) => {
      if (abortRef.current) return;
      let conversationId = activeIdRef.current;
      if (!conversationId) {
        try {
          const created = await api.createConversation(model);
          conversationId = created.id;
          setConversations((all) => [created, ...all]);
          skipLoadRef.current = created.id;
          navigate(created.id);
        } catch (e) {
          setError(`Could not start a conversation: ${errorText(e)}`);
          return;
        }
      }
      setMessages((all) => [
        ...all,
        placeholder(PENDING_USER, "user", text),
        placeholder(PENDING_REPLY, "assistant", "", model),
      ]);
      await runStream(conversationId, {
        method: "POST",
        path: `/api/conversations/${conversationId}/messages`,
        body: { content: text, model },
      });
    },
    [model, navigate, runStream],
  );

  const regenerate = useCallback(async () => {
    const conversationId = activeIdRef.current;
    if (!conversationId || abortRef.current) return;
    setMessages((all) => {
      const kept = [...all];
      while (kept.length && kept[kept.length - 1]?.role === "assistant") kept.pop();
      return [...kept, placeholder(PENDING_REPLY, "assistant", "", model)];
    });
    await runStream(conversationId, {
      method: "POST",
      path: `/api/conversations/${conversationId}/regenerate`,
      body: { model },
    });
  }, [model, runStream]);

  const edit = useCallback(
    async (messageId: string, content: string) => {
      const conversationId = activeIdRef.current;
      if (!conversationId || abortRef.current) return;
      setMessages((all) => {
        const index = all.findIndex((m) => m.id === messageId);
        const target = all[index];
        if (!target) return all;
        return [
          ...all.slice(0, index),
          { ...target, content },
          placeholder(PENDING_REPLY, "assistant", "", model),
        ];
      });
      await runStream(conversationId, {
        method: "PUT",
        path: `/api/conversations/${conversationId}/messages/${messageId}`,
        body: { content, model },
      });
    },
    [model, runStream],
  );

  const stop = useCallback(() => abortRef.current?.abort(), []);

  const selectConversation = useCallback(
    (id: string | null) => {
      if (id === activeIdRef.current) return;
      abortRef.current?.abort();
      navigate(id);
    },
    [navigate],
  );

  const renameConversation = useCallback(async (id: string, title: string) => {
    try {
      const updated = await api.updateConversation(id, { title });
      setConversations((all) => all.map((c) => (c.id === id ? updated : c)));
    } catch (e) {
      setError(`Could not rename: ${errorText(e)}`);
    }
  }, []);

  const deleteConversation = useCallback(
    async (id: string) => {
      if (id === streamConversationRef.current) abortRef.current?.abort();
      try {
        await api.deleteConversation(id);
        setConversations((all) => all.filter((c) => c.id !== id));
        if (activeIdRef.current === id) navigate(null);
      } catch (e) {
        setError(`Could not delete: ${errorText(e)}`);
      }
    },
    [navigate],
  );

  const chooseModel = useCallback((name: string) => {
    setModel(name);
    rememberModel(name);
    const id = activeIdRef.current;
    if (id) void api.updateConversation(id, { model: name }).catch(() => undefined);
  }, []);

  return {
    conversations,
    activeId,
    messages,
    models,
    model,
    streaming,
    loading,
    error,
    dismissError: () => setError(null),
    send,
    stop,
    regenerate,
    edit,
    selectConversation,
    renameConversation,
    deleteConversation,
    chooseModel,
    reloadModels: () => loadModels(true),
  };
}
