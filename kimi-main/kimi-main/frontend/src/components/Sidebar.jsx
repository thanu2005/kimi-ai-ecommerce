import { PlusIcon, MessageSquareIcon } from 'lucide-react';

export default function Sidebar({ conversations, activeThread, onSelectThread, onNewChat }) {
  return (
    <aside className="w-52 flex-shrink-0 border-r border-outline-variant flex flex-col bg-surface h-full">
      {/* Brand */}
      <div className="px-5 pt-5 pb-3">
        <h1 className="font-nabla text-[3rem] leading-none text-on-surface tracking-tight">
          kimi
        </h1>
        <p className="text-base text-black mt-1 leading-snug">
          Ai Ecommerce Brain Ops
        </p>
      </div>

      {/* New Chat */}
      <div className="px-4 pb-2">
        <button
          onClick={onNewChat}
          className="w-full flex items-center gap-2 text-sm text-on-surface-variant hover:text-on-surface transition-colors py-1.5 px-2 rounded-md hover:bg-surface-container-low"
        >
          <PlusIcon size={14} strokeWidth={2.5} />
          New Chat
        </button>
      </div>

      <div className="mx-4 border-t border-outline-variant" />

      {/* Recents */}
      <div className="flex-1 overflow-y-auto px-4 pt-3 pb-4">
        <p className="text-[11px] font-medium text-on-surface-variant mb-2 tracking-wider uppercase">
          Recents
        </p>

        {conversations.length === 0 ? (
          <p className="text-xs text-on-surface-variant opacity-50 px-1 leading-relaxed">
            No conversations yet
          </p>
        ) : (
          <ul className="space-y-0.5">
            {conversations.map((conv) => {
              const label =
                conv.title ||
                conv.initial_query ||
                conv.thread_id?.slice(0, 20) ||
                'Conversation';
              const isActive = activeThread === conv.thread_id;
              return (
                <li key={conv.thread_id}>
                  <button
                    onClick={() => onSelectThread(conv.thread_id)}
                    title={label}
                    className={`w-full flex items-center gap-2 text-left text-sm py-1.5 px-2 rounded-md transition-colors truncate ${
                      isActive
                        ? 'bg-surface-container text-on-surface font-medium'
                        : 'text-on-surface-variant hover:text-on-surface hover:bg-surface-container-low'
                    }`}
                  >
                    <MessageSquareIcon size={12} className="flex-shrink-0 opacity-60" />
                    <span className="truncate">{label}</span>
                  </button>
                </li>
              );
            })}
          </ul>
        )}
      </div>
    </aside>
  );
}
