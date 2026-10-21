const BASE = '';

export async function fetchConversations(limit = 50) {
  const res = await fetch(`${BASE}/api/conversations?limit=${limit}`);
  if (!res.ok) throw new Error(`Failed to fetch conversations: ${res.statusText}`);
  return res.json();
}

export async function fetchMessages(threadId, limit = 200) {
  const res = await fetch(`${BASE}/api/conversations/${encodeURIComponent(threadId)}/messages?limit=${limit}`);
  if (!res.ok) throw new Error(`Failed to fetch messages: ${res.statusText}`);
  return res.json();
}

/**
 * Stream a run via SSE. onEvent is called for each parsed SSE event object.
 * Events: {type: "trace", step, ...} | {type: "complete", ...} | {type: "error", message}
 */
export async function streamRunAnalysis(query, threadId, onEvent) {
  const body = { query };
  if (threadId) body.thread_id = threadId;

  const response = await fetch(`${BASE}/api/run/stream`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });

  if (!response.ok) {
    const err = await response.json().catch(() => ({ detail: response.statusText }));
    throw new Error(err.detail || 'Stream failed');
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const parts = buffer.split('\n\n');
    buffer = parts.pop(); // keep any incomplete final chunk
    for (const part of parts) {
      for (const line of part.split('\n')) {
        if (line.startsWith('data: ')) {
          try {
            onEvent(JSON.parse(line.slice(6)));
          } catch {
            // ignore malformed line
          }
        }
      }
    }
  }
}

export async function runAnalysis(query, threadId = null) {
  const body = { query };
  if (threadId) body.thread_id = threadId;

  const res = await fetch(`${BASE}/api/run`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || 'Analysis failed');
  }
  return res.json();
}

export async function resumeAnalysis({ threadId, approvedActions, rejectedActions = [], humanNote = '', runId = null }) {
  const body = {
    thread_id: threadId,
    approved_actions: approvedActions,
    rejected_actions: rejectedActions,
    human_note: humanNote,
  };
  if (runId) body.run_id = runId;

  const res = await fetch(`${BASE}/api/resume`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || 'Resume failed');
  }
  return res.json();
}
