import { useState, useEffect, useCallback, useRef } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import Sidebar from './components/Sidebar.jsx';
import ChatArea from './components/ChatArea.jsx';
import { fetchConversations, fetchMessages, streamRunAnalysis, resumeAnalysis } from './api/client.js';

function createClientThreadId() {
  // Keep a backend-compatible thread id shape while enabling instant URL routing.
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return `thread-${crypto.randomUUID().replace(/-/g, '').slice(0, 12)}`;
  }
  return `thread-${Date.now().toString(36)}${Math.random().toString(36).slice(2, 6)}`;
}

export default function App() {
  const { threadId } = useParams();
  const navigate = useNavigate();
  
  const [conversations, setConversations] = useState([]);
  const [activeThread, setActiveThread] = useState(null);
  const [messages, setMessages] = useState([]);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState(null);
  const [gifMode, setGifMode] = useState(false);
  const pendingRef = useRef(null);

  // Load conversations on mount
  useEffect(() => {
    loadConversations();
  }, []);
  
  // Sync activeThread with URL parameter
  useEffect(() => {
    if (threadId && threadId !== activeThread) {
      selectThread(threadId);
    } else if (!threadId && activeThread) {
      // If URL changes to home, clear active thread
      setActiveThread(null);
      setMessages([]);
    }
  }, [threadId]);

  const loadConversations = useCallback(async () => {
    try {
      const data = await fetchConversations();
      setConversations(data.conversations || []);
    } catch (e) {
      console.error('Sidebar load failed:', e);
    }
  }, []);

  const selectThread = useCallback(async (tid) => {
    if (activeThread === tid) return;

    // Navigate to thread URL
    navigate(`/${tid}`);

    setActiveThread(tid);
    setMessages([]);
    setError(null);
    pendingRef.current = null;
    setIsLoading(true);
    try {
      const data = await fetchMessages(tid);
      const rawMessages = data.messages || [];

      const loaded = rawMessages.map((m, i) => {
        const msg = {
          id: `hist-${tid}-${i}`,
          role: m.role,
          content: m.content ?? '',
          messageType: m.message_type ?? 'query',
          isHistory: true,
        };

        if (m.role === 'assistant') {
          if (m.formatted_response)         msg.formattedResponse = m.formatted_response;
          if (m.proposed_actions?.length)   msg.proposedActions   = m.proposed_actions;
          if (m.executed_actions?.length)   msg.executedActions   = m.executed_actions;
          if (m.action_effectiveness)       msg.actionEffectiveness = m.action_effectiveness;
          msg.runId    = m.run_id;
          msg.threadId = tid;
        }

        return msg;
      });

      // A live HITL interrupt can only be the very last message. If anything
      // follows the analysis message (an approval or completion), the interrupt
      // was already handled and must stay read-only.
      const last    = loaded[loaded.length - 1];
      const rawLast = rawMessages[rawMessages.length - 1];
      const isLiveInterrupt = (
        last?.role === 'assistant' &&
        last?.proposedActions?.length > 0 &&
        !last?.executedActions?.length &&
        !last?.formattedResponse
      );
      if (isLiveInterrupt) {
        last.isHistory      = false;
        last.actionsHandled = false;
        pendingRef.current  = { thread_id: tid, run_id: rawLast?.run_id };
      }

      setMessages(loaded);
    } catch (e) {
      setError('Could not load conversation history.');
    } finally {
      setIsLoading(false);
    }
  }, [activeThread, navigate]);

  const startNewChat = useCallback(() => {
    const nextThreadId = createClientThreadId();
    navigate(`/${nextThreadId}`);
    setActiveThread(nextThreadId);
    setMessages([]);
    setError(null);
    pendingRef.current = null;
  }, [navigate]);

  const handleSend = useCallback(async (query) => {
    if (!query.trim() || isLoading) return;
    setError(null);

    const userMsg = {
      id: `user-${Date.now()}`,
      role: 'user',
      content: query,
      messageType: 'query',
    };

    // Streaming assistant placeholder
    const streamId = `stream-${Date.now()}`;
    const streamingMsg = {
      id: streamId,
      role: 'assistant',
      content: '',
      messageType: 'streaming',
      trace: {
        selectedAgents: [],
        agentGoals: {},
        domainFindings: {},
        retrospectionDone: false,
        synthesizerDone: false,
        isStreaming: true,
      },
      whiteboard: {},
      proposedActions: [],
      executedActions: [],
      actionsHandled: false,
    };

    setMessages((prev) => [...prev, userMsg, streamingMsg]);
    setIsLoading(true);

    const updateTrace = (updater) => {
      setMessages((prev) =>
        prev.map((m) =>
          m.id === streamId
            ? { ...m, trace: { ...m.trace, ...updater(m.trace) } }
            : m
        )
      );
    };

    const currentThread = activeThread;

    try {
      await streamRunAnalysis(query, currentThread, (event) => {
        if (event.type === 'trace') {
          if (event.step === 'supervisor') {
            updateTrace(() => ({
              selectedAgents: event.selected_agents ?? [],
              agentGoals: event.agent_goals ?? {},
            }));
          } else if (event.step === 'domain_finding') {
            updateTrace((t) => ({
              domainFindings: {
                ...t.domainFindings,
                [event.domain]: event.findings ?? [],
              },
            }));
          } else if (event.step === 'retrospection') {
            updateTrace(() => ({ retrospectionDone: true }));
          } else if (event.step === 'synthesizer') {
            updateTrace(() => ({ synthesizerDone: true }));
          } else if (event.step === 'response_formatter') {
            updateTrace(() => ({ formatterDone: true }));
          }
        } else if (event.type === 'complete') {
          const {
            thread_id,
            run_id,
            status,
            proposed_actions = [],
            whiteboard = {},
            formatted_response = '',
            action_effectiveness = {},
            off_topic = false,
          } = event;

          // Always sync active thread + URL from backend response.
          // This avoids stale callback state leaving the URL at '/'.
          setActiveThread(thread_id);
          if (thread_id && thread_id !== currentThread) {
            navigate(`/${thread_id}`);
          }
          if (!currentThread) {
            loadConversations();
          }

          if (status === 'awaiting_approval') {
            pendingRef.current = { thread_id, run_id };
          } else {
            pendingRef.current = null;
            if (!currentThread) loadConversations();
          }

          setMessages((prev) =>
            prev.map((m) =>
              m.id === streamId
                ? {
                    ...m,
                    messageType: status === 'awaiting_approval' ? 'analysis' : 'completion',
                    whiteboard,
                    formattedResponse: formatted_response,
                    proposedActions: proposed_actions,
                    actionEffectiveness: action_effectiveness,
                    runId: run_id,
                    threadId: thread_id,
                    status,
                    trace: { ...m.trace, isStreaming: false, offTopic: off_topic },
                  }
                : m
            )
          );
          setIsLoading(false);
        } else if (event.type === 'error') {
          setError(event.message);
          setMessages((prev) =>
            prev.map((m) =>
              m.id === streamId
                ? { ...m, trace: { ...m.trace, isStreaming: false } }
                : m
            )
          );
          setIsLoading(false);
        }
      });
    } catch (e) {
      setError(e.message);
      setMessages((prev) =>
        prev.map((m) =>
          m.id === streamId
            ? { ...m, trace: { ...m.trace, isStreaming: false } }
            : m
        )
      );
      setIsLoading(false);
    }
  }, [isLoading, navigate, loadConversations, activeThread]);

  const handleApproval = useCallback(async (messageId, { approvedActions, rejectedActions, humanNote }) => {
    const pending = pendingRef.current;
    if (!pending) return;
    setIsLoading(true);
    setError(null);

    setMessages((prev) =>
      prev.map((m) => {
        if (m.id !== messageId) return m;
        const updated = { ...m, actionsHandled: true };
        if (m.trace) {
          updated.trace = {
            ...m.trace,
            wasRejected: rejectedActions.length > 0,
            wasApproved: rejectedActions.length === 0,
          };
        }
        return updated;
      })
    );

    try {
      const result = await resumeAnalysis({
        threadId: pending.thread_id,
        approvedActions,
        rejectedActions,
        humanNote,
        runId: pending.run_id,
      });

      const resumeMsg = {
        id: `resume-${result.run_id ?? Date.now()}`,
        role: 'assistant',
        content: '',
        messageType: result.status === 'awaiting_approval' ? 'analysis' : 'completion',
        whiteboard: result.whiteboard ?? {},
        formattedResponse: (result.whiteboard ?? {}).formatted_response ?? '',
        proposedActions: result.proposed_actions ?? [],
        executedActions: result.executed_actions ?? [],
        actionEffectiveness: result.action_effectiveness ?? {},
        runId: result.run_id ?? pending.run_id,
        threadId: result.thread_id ?? pending.thread_id,
        status: result.status,
        actionsHandled: false,
        isResume: true,
      };
      setMessages((prev) => {
        const withResume = [...prev, resumeMsg];

        // When the whole flow is done, reset every trace panel to the
        // fully-completed state so no stale wasRejected / formatterDone=false
        // flags remain visible in either standard or GIF mode.
        if (result.status === 'completed') {
          return withResume.map((m) =>
            m.trace
              ? {
                  ...m,
                  trace: {
                    ...m.trace,
                    formatterDone: true,
                    isStreaming:   false,
                    wasRejected:   false,
                    wasApproved:   false,
                  },
                }
              : m
          );
        }

        return withResume;
      });

      if (result.status === 'awaiting_approval') {
        pendingRef.current = { thread_id: resumeMsg.threadId, run_id: resumeMsg.runId };
      } else {
        pendingRef.current = null;
        loadConversations();
      }
    } catch (e) {
      setError(e.message);
    } finally {
      setIsLoading(false);
    }
  }, [loadConversations]);

  return (
    <div className="flex h-screen overflow-hidden bg-surface">
      <Sidebar
        conversations={conversations}
        activeThread={activeThread}
        onSelectThread={selectThread}
        onNewChat={startNewChat}
      />
      <ChatArea
        messages={messages}
        isLoading={isLoading}
        error={error}
        activeThread={activeThread}
        onSend={handleSend}
        onApproval={handleApproval}
        gifMode={gifMode}
        onToggleGifMode={() => setGifMode((g) => !g)}
      />
    </div>
  );
}
