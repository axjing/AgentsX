export interface Message {
  role: "system" | "user" | "assistant" | "tool";
  content: string;
  id?: string;
}

export interface ToolCall {
  id: string;
  name: string;
  arguments: Record<string, unknown>;
}

export interface Session {
  id: string;
  title: string;
  model_name: string;
  created_at: string;
  updated_at: string;
}
