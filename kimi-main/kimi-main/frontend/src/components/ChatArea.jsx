import { useEffect, useRef } from 'react';
import Message from './Message.jsx';
import InputBar from './InputBar.jsx';

function EmptyState() {
  return (
    <div className="flex flex-col items-center justify-center gap-2 pb-8 select-none pointer-events-none">
      <h2 className="font-annie-use-your-telescope text-6xl text-on-surface/80 leading-none">kimi</h2>
      <p className="text-xl text-on-surface-variant/80">Ask anything about your operations</p>
    </div>
  );
}

function GifToggle({ gifMode, onToggle }) {
  return (
    <button
      role="switch"
      aria-checked={gifMode}
      onClick={onToggle}
      className="flex items-center gap-2 px-3 py-1.5 rounded-full border text-xs font-medium transition-all select-none
        bg-surface-container border-outline-variant text-on-surface-variant
        hover:bg-surface-container-high"
      title="Toggle GIF thinking mode"
    >
      <span className="leading-none">✨</span>
      <span>GIF Mode</span>
      {/* pill switch */}
      <div className={`relative ml-0.5 flex h-4 w-7 items-center rounded-full transition-colors duration-200
        ${gifMode ? 'bg-primary' : 'bg-outline-variant'}`}>
        <span className={`absolute h-3 w-3 rounded-full bg-white shadow transition-transform duration-200
          ${gifMode ? 'translate-x-3.5' : 'translate-x-0.5'}`} />
      </div>
    </button>
  );
}

export default function ChatArea({ messages, isLoading, error, activeThread, onSend, onApproval, gifMode, onToggleGifMode }) {
  const bottomRef = useRef(null);
  const hasMessages = messages.length > 0;

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, isLoading]);

  return (
    <main className="relative flex-1 flex flex-col h-full overflow-hidden">
      {/* Toggle — centered at the top */}
      <div className="flex-shrink-0 flex justify-center pt-3 pb-1 z-20">
        <GifToggle gifMode={gifMode} onToggle={onToggleGifMode} />
      </div>

      {/* Message list */}
      <div className="flex-1 overflow-y-auto">
        {!hasMessages && !isLoading ? (
          <div className="h-full flex flex-col items-center justify-center gap-8 px-6">
            <EmptyState />
            <div className="w-full max-w-2xl">
              <InputBar onSend={onSend} disabled={isLoading} />
            </div>
          </div>
        ) : (
          <div className="px-4 pt-6 pb-4 space-y-1 max-w-3xl mx-auto w-full">
            {messages.map((msg) => (
              <Message key={msg.id} message={msg} onApproval={onApproval} gifMode={gifMode} />
            ))}

            {error && (
              <div className="animate-fade-in mx-2 my-3 px-4 py-3 rounded-xl bg-error-container border border-error/20 text-sm text-error">
                <strong>Error:</strong> {error}
              </div>
            )}

            <div ref={bottomRef} />
          </div>
        )}
      </div>

      {/* Pinned input – only show when messages are present */}
      {hasMessages && (
        <div className="flex-shrink-0 px-4 py-4 border-t border-outline-variant/40">
          <div className="max-w-3xl mx-auto">
            <InputBar onSend={onSend} disabled={isLoading} />
          </div>
        </div>
      )}
    </main>
  );
}
