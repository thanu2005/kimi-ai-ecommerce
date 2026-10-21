import { useState, useRef, useCallback } from 'react';
import { ArrowUpIcon } from 'lucide-react';

export default function InputBar({ onSend, disabled }) {
  const [value, setValue] = useState('');
  const textareaRef = useRef(null);

  const submit = useCallback(() => {
    const trimmed = value.trim();
    if (!trimmed || disabled) return;
    onSend(trimmed);
    setValue('');
    if (textareaRef.current) {
      textareaRef.current.style.height = 'auto';
    }
  }, [value, disabled, onSend]);

  const handleKeyDown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      submit();
    }
  };

  const handleInput = (e) => {
    const ta = e.target;
    ta.style.height = 'auto';
    ta.style.height = `${Math.min(ta.scrollHeight, 180)}px`;
    setValue(ta.value);
  };

  const canSend = value.trim().length > 0 && !disabled;

  return (
    <div className="flex items-end gap-2 px-4 py-3 rounded-full border border-outline-variant bg-surface shadow-sm focus-within:border-primary transition-colors">
      <textarea
        ref={textareaRef}
        value={value}
        onInput={handleInput}
        onKeyDown={handleKeyDown}
        placeholder="Ask me anything about your operations…"
        rows={1}
        disabled={disabled}
        className="flex-1 resize-none bg-transparent text-sm text-on-surface placeholder:text-on-surface-variant/60 focus:outline-none leading-relaxed py-0.5 max-h-44 overflow-y-auto disabled:opacity-50"
        style={{ height: 'auto' }}
      />
      <button
        onClick={submit}
        disabled={!canSend}
        aria-label="Send"
        className={`flex-shrink-0 w-8 h-8 rounded-full flex items-center justify-center transition-all ${
          canSend
            ? 'bg-surface-container text-on-surface shadow-sm hover:bg-surface-container/80 active:scale-95'
            : 'bg-surface-container-high text-on-surface-variant/40 cursor-not-allowed'
        }`}
      >
        <ArrowUpIcon size={15} strokeWidth={2.5} />
      </button>
    </div>
  );
}
