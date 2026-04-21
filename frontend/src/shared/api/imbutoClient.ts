/* ── IMBUTO — API Client ─────────────────────────────────── */

const BASE_URL = import.meta.env.VITE_API_URL || (window as any).imbuto?.apiUrl || "http://localhost:8000";

/* ── Response types ────────────────────────────────────────────────── */

export interface QueryResponse {
    answer: string;
    context: ContextSource[];
}

export interface ContextSource {
    file: string;
    content: string;
    chunk: string;
    source_file: string;
    score: number;
    distance: number;
}

export interface SaveResponse {
    saved: boolean;
    path: string;
    synced_chunks: number;
}

export interface HealthResponse {
    status: string;
    vector_db: string;
}

export interface SystemStatusResponse {
    status: string;
    version: string;
    workspace: string;
    document_count: number;
    chunk_count: number;
    last_sync_time: string | null;
}

export interface WorkspaceInfo {
    workspace_id: string;
    name: string;
    paths: string[];
    global_fallback: boolean;
}

export interface FileMetadata {
    name: string;
    path: string;
    size: number;
    last_modified: string;
}

export interface FileDetail {
    name: string;
    path: string;
    content: string;
    size: number;
    last_modified: string;
    token_count: number;
    chunk_count: number;
    wikilinks: string[];
}

export interface GraphNode {
    id: string;
    name: string;
    group: string;
}

export interface GraphLink {
    source: string;
    target: string;
    type: "structural" | "semantic";
    weight: number;
    reason?: string;
}

export interface GraphDataResponse {
    nodes: GraphNode[];
    links: GraphLink[];
}

export interface BlacklistResponse {
    pairs: string[][];
}

export interface FilesListResponse {
    workspace_id: string | null;
    files: FileMetadata[];
}

/* ── Custom error with status code ─────────────────────────────────── */

export class ApiError extends Error {
    status: number;
    constructor(status: number, body: string) {
        super(`API ${status}: ${body}`);
        this.status = status;
        this.name = "ApiError";
    }
}

/* ── Generic fetch wrapper ─────────────────────────────────────────── */

async function request<T>(
    path: string,
    options: RequestInit = {},
): Promise<T> {
    const token = (window as any).imbuto?.internalToken || "";
    const res = await fetch(`${BASE_URL}${path}`, {
        headers: { "Content-Type": "application/json", "X-Internal-Token": token, ...options.headers },
        ...options,
    });

    if (!res.ok) {
        const body = await res.text();
        throw new ApiError(res.status, body);
    }

    return res.json() as Promise<T>;
}

/* ── Service functions ─────────────────────────────────────────────── */

/** Query the RAG pipeline — returns LLM answer + retrieved context sources. */
export async function queryMemory(
    prompt: string,
    workspace = "ws-default",
    model = "",
    currentFileContext = "",
    cursorPosition = 0,
): Promise<QueryResponse> {
    return request<QueryResponse>("/api/query", {
        method: "POST",
        body: JSON.stringify({
            query: prompt,
            workspace_id: workspace,
            model,
            ...(currentFileContext ? { current_file_context: currentFileContext } : {}),
            cursor_position: cursorPosition,
        }),
    });
}

/** Save a markdown document and trigger incremental ChromaDB sync. */
export async function syncDocument(
    filename: string,
    content: string,
    workspaceId = "ws-default",
): Promise<SaveResponse> {
    return request<SaveResponse>("/api/save", {
        method: "POST",
        body: JSON.stringify({
            filename,
            content,
            workspace_id: workspaceId,
        }),
    });
}

/** List vault files with metadata, optionally scoped by workspace. */
export async function listFiles(
    workspaceId?: string,
): Promise<FilesListResponse> {
    const params = workspaceId ? `?workspace_id=${encodeURIComponent(workspaceId)}` : "";
    return request<FilesListResponse>(`/api/files${params}`);
}

/** Get full file content + Inspector metadata (tokens, chunks, wikilinks). */
export async function getFile(filePath: string): Promise<FileDetail> {
    // Encode each path segment individually to preserve "/" separators
    const safePath = filePath.split("/").map(encodeURIComponent).join("/");
    return request<FileDetail>(`/api/files/${safePath}`);
}

/** Liveness probe. */
export async function checkHealth(): Promise<HealthResponse> {
    return request<HealthResponse>("/health");
}

/** Get full system status including document counts. */
export async function getSystemStatus(workspaceId?: string): Promise<SystemStatusResponse> {
    const params = workspaceId ? `?workspace_id=${encodeURIComponent(workspaceId)}` : "";
    return request<SystemStatusResponse>(`/api/status${params}`);
}

/** Get global vault graph of wikilink connections, optionally scoped by folder. */
export async function getGraphData(folderPath?: string): Promise<GraphDataResponse> {
    const params = folderPath ? `?folder_path=${encodeURIComponent(folderPath)}` : "";
    return request<GraphDataResponse>(`/api/graph${params}`);
}

/** List all registered workspaces. */
export async function listWorkspaces(): Promise<WorkspaceInfo[]> {
    return request<WorkspaceInfo[]>("/api/workspaces");
}

/** Get all blacklisted (ignored) link pairs. */
export async function getBlacklist(): Promise<BlacklistResponse> {
    return request<BlacklistResponse>("/api/graph/blacklist");
}

/** Add a link pair to the blacklist. */
export async function addToBlacklist(source: string, target: string): Promise<BlacklistResponse> {
    return request<BlacklistResponse>("/api/graph/blacklist", {
        method: "POST",
        body: JSON.stringify({ source, target }),
    });
}

/** Remove a link pair from the blacklist. */
export async function removeFromBlacklist(source: string, target: string): Promise<BlacklistResponse> {
    return request<BlacklistResponse>("/api/graph/blacklist", {
        method: "DELETE",
        body: JSON.stringify({ source, target }),
    });
}
