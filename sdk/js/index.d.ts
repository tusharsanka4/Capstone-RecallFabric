/**
 * TypeScript definitions for RecallFabric Client SDK.
 */

export type MemoryType = 'preference' | 'goal' | 'skill' | 'profile' | 'fact' | 'other';

export interface Memory {
  id: string;
  user_id: string;
  content: string;
  type: MemoryType;
  importance: number;
  confidence: number;
  source: string;
  version: number;
  status: string;
  created_at?: string;
  updated_at?: string;
  attributes?: Record<string, any>;
}

export interface RememberOptions {
  content?: string;
  text?: string;
  type?: MemoryType;
  importance?: number;
  confidence?: number;
  source?: string;
  extract?: boolean;
  userId?: string;
  metadata?: Record<string, any>;
  idempotencyKey?: string;
}

export interface RememberResult {
  status: string;
  action: string;
  memory: Memory | null;
  memories: Memory[];
  count: number;
  message: string;
}

export interface RecallItem {
  id: string;
  user_id: string;
  content: string;
  type: MemoryType;
  importance: number;
  confidence: number;
  source: string;
  version: number;
  score: number;
  similarity?: number | null;
  metadata?: Record<string, any>;
}

export interface RecallOptions {
  query: string;
  limit?: number;
  type?: MemoryType;
  minSimilarity?: number;
  userId?: string;
}

export interface RecallResult {
  context: string;
  memories: RecallItem[];
  count: number;
  query: string;
}

export interface ForgetOptions {
  memoryId?: string;
  query?: string;
  confirm?: boolean;
  userId?: string;
}

export interface ForgetResult {
  confirmed: boolean;
  status: 'deleted' | 'pending_confirmation' | 'not_found';
  deleted_id?: string | null;
  candidate?: Memory | null;
  deleted_memory?: Memory | null;
  message: string;
}

export interface ProfileOptions {
  userId?: string;
  limit?: number;
}

export interface ProfileResult {
  user_id: string;
  summary: string;
  memory_count: number;
  categories: Record<string, string[]>;
  memories: Memory[];
}

export interface CapabilitiesResult {
  service: string;
  service_version: string;
  api_version: string;
  supported_memory_types: string[];
  embedding_model: string;
  embedding_dimensions: number;
  enabled_features: Record<string, boolean>;
  limits: Record<string, any>;
}

export interface ListMemoriesOptions {
  userId?: string;
  status?: string;
  type?: MemoryType;
  limit?: number;
  offset?: number;
}

export interface UpdateMemoryOptions {
  content?: string;
  type?: MemoryType;
  importance?: number;
  userId?: string;
}

export interface ClientConfig {
  baseUrl?: string;
  apiKey?: string;
  userId?: string;
  timeoutMs?: number;
  maxRetries?: number;
  backoffFactor?: number;
}

export class RecallFabricError extends Error {
  code: string;
  statusCode?: number;
  details?: any;
}

export class APIError extends RecallFabricError {
  constructor(statusCode: number, message: string, code?: string, details?: any);
}

export class AuthenticationError extends APIError {}
export class PermissionDeniedError extends APIError {}
export class NotFoundError extends APIError {}
export class RateLimitError extends APIError {}
export class TimeoutError extends RecallFabricError {}
export class ConnectionError extends RecallFabricError {}

export class RecallFabric {
  constructor(config?: ClientConfig);

  remember(options: RememberOptions | string): Promise<RememberResult>;
  recall(options: RecallOptions | string): Promise<RecallResult>;
  forget(options: ForgetOptions): Promise<ForgetResult>;
  profile(options?: ProfileOptions): Promise<ProfileResult>;
  capabilities(): Promise<CapabilitiesResult>;
  list(options?: ListMemoriesOptions): Promise<Memory[]>;
  update(memoryId: string, options: UpdateMemoryOptions): Promise<Memory>;
}

export interface ChatMessage {
  role: 'system' | 'user' | 'assistant' | string;
  content: string;
}

export interface WithMemoryOptions {
  userId?: string;
  extractAfter?: boolean;
  limit?: number;
  minSimilarity?: number;
  contextTemplate?: string;
}

export function withMemory<T extends (messages: ChatMessage[]) => Promise<any>>(
  llmCall: T,
  client: RecallFabric,
  options?: WithMemoryOptions
): (messages: ChatMessage[]) => Promise<any>;
