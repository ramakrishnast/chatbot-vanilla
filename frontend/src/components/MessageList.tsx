import { useEffect, useRef } from "react";

import type { Message } from "../types";
import { MessageItem } from "./MessageItem";

interface Props {
  messages: Message[];
  streaming: boolean;
  onRegenerate: () => void;
  onEdit: (messageId: string, content: string) => void;
}

const STICK_THRESHOLD_PX = 80;

export function MessageList({ messages, streaming, onRegenerate, onEdit }: Props) {
  const scroller = useRef<HTMLDivElement>(null);
  // Follow new tokens only while the reader is at the bottom; scrolling up pauses it.
  const stickToBottom = useRef(true);

  useEffect(() => {
    const el = scroller.current;
    if (el && stickToBottom.current) el.scrollTop = el.scrollHeight;
  }, [messages]);

  const onScroll = () => {
    const el = scroller.current;
    if (!el) return;
    stickToBottom.current = el.scrollHeight - el.scrollTop - el.clientHeight < STICK_THRESHOLD_PX;
  };

  return (
    <div className="messages" ref={scroller} onScroll={onScroll}>
      <div className="messages-inner">
        {messages.map((message, index) => (
          <MessageItem
            key={message.id}
            message={message}
            isLast={index === messages.length - 1}
            canAct={!streaming}
            onRegenerate={onRegenerate}
            onEdit={onEdit}
          />
        ))}
      </div>
    </div>
  );
}
