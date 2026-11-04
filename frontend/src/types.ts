export type Role = "user" | "assistant";

/** "streaming" only exists in the browser while a reply is arriving. */
export type MessageStatus = "complete" | "stopped" | "error" | "streaming";

export interface Message {
  id: string;
  position: number;
  role: Role;
  content: string;
  thinking: string | null;
  model: string | null;
  status: MessageStatus;
  created_at: string;
}

export interface ConversationSummary {
  id: string;
  title: string;
  model: string | null;
  created_at: string;
  updated_at: string;
}

export interface ConversationDetail extends ConversationSummary {
  messages: Message[];
}

export interface ModelInfo {
  name: string;
  size: number | null;
  parameter_size: string | null;
  family: string | null;
  capabilities: string[];
}

export interface ModelList {
  models: ModelInfo[];
  default: string | null;
}

/** One line of the NDJSON stream returned by the send / regenerate / edit endpoints. */
export type StreamEvent =
  | { type: "user_message"; message: Message }
  | { type: "thinking"; content: string }
  | { type: "delta"; content: string }
  | { type: "error"; detail: string }
  | { type: "title"; title: string }
  | { type: "done"; message: Message | null };
