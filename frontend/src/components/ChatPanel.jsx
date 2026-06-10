import { useEffect, useMemo, useRef, useState } from 'react';
import { Bot, CornerDownLeft, History, Loader2, Plus, Search, Send, Square, Trash2, User } from 'lucide-react';
import { MarkdownBlock } from './MarkdownBlock.jsx';

export function ChatPanel({
  apiBase,
  status,
  activeAgent,
  agentDetails,
  resources,
  capabilities,
  diagnostics,
  runtimeStatus,
  sessions,
  activeSessionId,
  sessionsLoading,
  createSession,
  selectSession,
  deleteSession,
  messages,
  isRunning,
  sendMessage,
}) {
  const [draft, setDraft] = useState('');
  const messageListRef = useRef(null);
  const textareaRef = useRef(null);
  const isComposingRef = useRef(false);
  const runtimeFailed = runtimeStatus === 'failed';
  const chatTitle = useMemo(() => activeAgent?.name ? `和 ${activeAgent.name} 聊天` : '选择智能体后开始聊天', [activeAgent]);
  const runningAssistantId = isRunning
    ? messages.slice().reverse().find((message) => message.role === 'assistant')?.id
    : '';

  useEffect(() => {
    const textarea = textareaRef.current;
    if (!textarea) return;
    textarea.style.height = '0px';
    const nextHeight = Math.min(Math.max(textarea.scrollHeight, 34), 148);
    textarea.style.height = `${nextHeight}px`;
    textarea.style.overflowY = textarea.scrollHeight > 148 ? 'auto' : 'hidden';
  }, [draft]);

  useEffect(() => {
    const list = messageListRef.current;
    if (!list) return;
    list.scrollTo({ top: list.scrollHeight, behavior: 'smooth' });
  }, [messages.length, isRunning]);

  function submit(event) {
    event.preventDefault();
    if (!draft.trim() || !activeAgent || isRunning || runtimeFailed) return;
    sendMessage(draft);
    setDraft('');
  }

  function handleKeyDown(event) {
    if (
      event.key === 'Enter'
      && !event.shiftKey
      && !event.nativeEvent.isComposing
      && !isComposingRef.current
    ) {
      event.preventDefault();
      submit(event);
    }
  }

  return (
    <section className="main-panel">
      <div className="chat-body">
        <SessionRail
          sessions={sessions}
          activeSessionId={activeSessionId}
          sessionsLoading={sessionsLoading}
          createSession={createSession}
          selectSession={selectSession}
          deleteSession={deleteSession}
          disabled={!activeAgent || isRunning}
        />
        <section className="conversation" aria-label={chatTitle}>
          <div className="message-list" ref={messageListRef}>
            {messages.map((message) => (
              <ChatMessage
                key={message.id}
                message={message}
                isThinking={message.id === runningAssistantId}
              />
            ))}
          </div>
          <form className="composer" onSubmit={submit}>
            <div className="composer-card">
              <textarea
                ref={textareaRef}
                rows={1}
                value={draft}
                onChange={(event) => setDraft(event.target.value)}
                onCompositionStart={() => { isComposingRef.current = true; }}
                onCompositionEnd={() => { isComposingRef.current = false; }}
                onKeyDown={handleKeyDown}
                placeholder={runtimeFailed ? diagnosticPlaceholder(diagnostics) : activeAgent ? '输入消息...' : '请先在左侧选择或创建智能体'}
                disabled={!activeAgent || isRunning || runtimeFailed}
              />
              <div className="composer-footer">
                <span className="composer-hint"><CornerDownLeft size={13} />Enter 发送，Shift + Enter 换行</span>
                <button className="send-button" type="submit" disabled={!activeAgent || isRunning || runtimeFailed || !draft.trim()} title="发送消息">
                  {isRunning ? <Square size={16} /> : <Send size={16} />}
                  <span>{isRunning ? '运行中' : '发送'}</span>
                </button>
              </div>
            </div>
          </form>
        </section>
      </div>
    </section>
  );
}

function SessionRail({
  sessions = [],
  activeSessionId,
  sessionsLoading,
  createSession,
  selectSession,
  deleteSession,
  disabled,
}) {
  const [query, setQuery] = useState('');
  const normalizedQuery = query.trim().toLowerCase();
  const filteredSessions = useMemo(() => {
    if (!normalizedQuery) return sessions;
    return sessions.filter((session) => sessionSearchText(session).includes(normalizedQuery));
  }, [normalizedQuery, sessions]);

  return (
    <aside className="session-rail">
      <div className="session-rail-head">
        <strong><History size={15} />历史对话</strong>
        <button className="icon-button session-create-button" onClick={() => createSession()} disabled={disabled} title="新建对话" aria-label="新建对话">
          <Plus size={15} />
        </button>
      </div>
      <label className="session-search">
        <Search size={14} />
        <input
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder="搜索历史对话"
          disabled={sessionsLoading || !sessions.length}
        />
      </label>
      <div className="session-list">
        {sessionsLoading && <div className="session-empty">正在加载会话...</div>}
        {!sessionsLoading && filteredSessions.map((session) => (
          <article className={session.id === activeSessionId ? 'session-item active' : 'session-item'} key={session.id}>
            <button type="button" onClick={() => selectSession(session.id)} disabled={disabled && session.id !== activeSessionId}>
              <strong>{session.title || '新会话'}</strong>
              <span>{formatSessionTime(session.last_message_at || session.updated_at || session.created_at)}</span>
            </button>
            <button
              className="session-delete"
              type="button"
              onClick={(event) => {
                event.stopPropagation();
                deleteSession(session.id);
              }}
              disabled={disabled}
              title="删除会话"
              aria-label="删除会话"
            >
              <Trash2 size={13} />
            </button>
          </article>
        ))}
        {!sessionsLoading && !sessions.length && (
          <div className="session-empty">还没有历史会话，发送消息或点击新建。</div>
        )}
        {!sessionsLoading && Boolean(sessions.length) && !filteredSessions.length && (
          <div className="session-empty">没有匹配的历史对话。</div>
        )}
      </div>
    </aside>
  );
}

function sessionSearchText(session) {
  return [
    session.title || '新会话',
    formatSessionTime(session.last_message_at || session.updated_at || session.created_at),
  ].join(' ').toLowerCase();
}

function formatSessionTime(value) {
  if (!value) return '未开始';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  });
}

function diagnosticPlaceholder(diagnostics = []) {
  const first = diagnostics.find((diagnostic) => diagnostic.severity === 'error') || diagnostics[0];
  return first ? `运行时不可用：${first.message}` : '运行时不可用，请检查插件依赖';
}

function ChatMessage({ message, isThinking = false }) {
  const isUser = message.role === 'user';
  const hasContent = hasMessageContent(message);
  return (
    <article className={isUser ? 'message user' : 'message assistant'}>
      <div className="avatar">{isUser ? <User size={15} /> : <Bot size={15} />}</div>
      <div className={isThinking && !hasContent ? 'bubble thinking-bubble' : 'bubble'}>
        <div className="message-author">{isUser ? '你' : 'Agent'}</div>
        {isThinking && !hasContent ? (
          <ThinkingIndicator />
        ) : (
          <>
            <MarkdownBlock content={message.content} />
            {isThinking && <ThinkingNote />}
          </>
        )}
        {message.meta?.tool_calls?.length > 0 && (
          <details>
            <summary>工具调用 {message.meta.tool_calls.length} 次</summary>
            <pre>{JSON.stringify(message.meta.tool_calls, null, 2)}</pre>
          </details>
        )}
      </div>
    </article>
  );
}

function hasMessageContent(message) {
  return Boolean(String(message.content || '').trim() || message.meta?.tool_calls?.length);
}

function ThinkingIndicator() {
  return (
    <span className="typing-inline">
      <span>正在思考并调用插件</span>
      <i />
      <i />
      <i />
    </span>
  );
}

function ThinkingNote() {
  return (
    <span className="message-running-note">
      <Loader2 size={13} className="spin" />
      正在处理
    </span>
  );
}
