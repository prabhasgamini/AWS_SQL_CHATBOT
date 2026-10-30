export interface Timings {
  guardrails_ms: number;
  llm_ms: number;
  sql_ms: number;
  total_ms: number;
}

export interface TokenUsage {
  input_tokens: number;
  output_tokens: number;
  total_tokens: number;
}

export interface User {
  username: string;
  role: "admin" | "user";
  display_name: string;
  consumer_number: string | null;
}

export interface Calculation {
  metric?: string;
  headline?: string;
  formula?: string;
  inputs?: Record<string, unknown>;
  result?: Record<string, unknown>;
  assessment?: string;
  notes?: string[];
}

export type Row = Record<string, string | number | null>;

export interface ChatApiResponse {
  session_id: string;
  response: string;
  generated_sql: string | null;
  columns: string[];
  data: Row[];
  truncated: boolean;
  blocked: boolean;
  tools_used: string[];
  calculations: Calculation[];
  timings: Timings;
  token_usage: TokenUsage;
}

export interface Message {
  id: string;
  role: "user" | "assistant";
  content: string;
  isError?: boolean;
  sql?: string | null;
  columns?: string[];
  data?: Row[];
  truncated?: boolean;
  calculations?: Calculation[];
  timings?: Timings;
  tokens?: TokenUsage;
}

export interface Session {
  id: string;
  title: string;
  messages: Message[];
  updatedAt: number;
}
