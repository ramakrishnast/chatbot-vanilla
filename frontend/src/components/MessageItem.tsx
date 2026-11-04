import { memo, useState, type KeyboardEvent } from "react";

import type { Message } from "../types";
import { copyText } from "./copy";
import { Markdown } from "./Markdown";

interface Props {
  message: Message;
  isLast: boolean;
  canAct: boolean;
  onRegenerate: () => void;
  onEdit: (messageId: string, content: string) => void;
}

const isSaved = (message: Message) => !message.id.startsWith("pending-");

function UserMessage({ message, canAct, onEdit }: Omit<Props, "isLast" | "onRegenerate">) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(message.content);

  const save = () => {
    const value = draft.trim();
    if (!value) return;
    setEditing(false);
    if (value !== message.content) onEdit(message.id, value);
  };

  const onKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === "Escape") setEditing(false);
    if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
      event.preventDefault();
      save();
    }
  };

  if (editing) {
    return (
      <div className="message user editing">
        <textarea
          aria-label="Edit message"
          value={draft}
          autoFocus
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={onKeyDown}
        />
        <div className="edit-actions">
          <button type="button" className="secondary" onClick={() => setEditing(false)}>
            Cancel
          </button>
          <button type="button" className="primary" onClick={save} disabled={!draft.trim()}>
            Save &amp; submit
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="message user">
      <div className="bubble">{message.content}</div>
      {canAct && isSaved(message) && (
        <div className="message-actions">
          <button
            type="button"
            onClick={() => {
              setDraft(message.content);
              setEditing(true);
            }}
          >
            Edit
          </button>
        </div>
      )}
    </div>
  );
}

function AssistantMessage({ message, isLast, canAct, onRegenerate }: Omit<Props, "onEdit">) {
  const [copied, setCopied] = useState(false);
  const live = message.status === "streaming";
  const waiting = live && !message.content && !message.thinking;

  const copy = async () => {
    if (await copyText(message.content)) {
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1500);
    }
  };

  return (
    <div className="message assistant" aria-busy={live}>
      {message.thinking && (
        <details className="thinking" open={live && !message.content}>
          <summary>{live && !message.content ? "Thinking…" : "Thought process"}</summary>
          <div className="thinking-body">{message.thinking}</div>
        </details>
      )}
      {waiting ? (
        <div className="typing" aria-label="Waiting for reply">
          <span />
          <span />
          <span />
        </div>
      ) : (
        message.content && <Markdown text={message.content} />
      )}
      {message.status === "stopped" && <p className="note">Stopped.</p>}
      {message.status === "error" && <p className="note error">The reply failed.</p>}
      {!live && (
        <div className="message-actions">
          {message.content && (
            <button type="button" onClick={copy}>
              {copied ? "Copied" : "Copy"}
            </button>
          )}
          {isLast && canAct && (
            <button type="button" onClick={onRegenerate}>
              Regenerate
            </button>
          )}
          {message.model && <span className="model-tag">{message.model}</span>}
        </div>
      )}
    </div>
  );
}

export const MessageItem = memo(function MessageItem(props: Props) {
  return props.message.role === "user" ? (
    <UserMessage message={props.message} canAct={props.canAct} onEdit={props.onEdit} />
  ) : (
    <AssistantMessage
      message={props.message}
      isLast={props.isLast}
      canAct={props.canAct}
      onRegenerate={props.onRegenerate}
    />
  );
});
