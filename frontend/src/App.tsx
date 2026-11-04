import { useState } from "react";

import { Composer } from "./components/Composer";
import { MessageList } from "./components/MessageList";
import { ModelPicker } from "./components/ModelPicker";
import { Sidebar } from "./components/Sidebar";
import { useChat } from "./useChat";

export default function App() {
  const chat = useChat();
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const activeTitle = chat.conversations.find((c) => c.id === chat.activeId)?.title;
  const empty = chat.messages.length === 0 && !chat.loading;

  return (
    <div className="app">
      <Sidebar
        conversations={chat.conversations}
        activeId={chat.activeId}
        open={sidebarOpen}
        onClose={() => setSidebarOpen(false)}
        onSelect={(id) => {
          chat.selectConversation(id);
          setSidebarOpen(false);
        }}
        onRename={chat.renameConversation}
        onDelete={chat.deleteConversation}
      />

      <main className="main">
        <header className="topbar">
          <button
            className="icon-button menu-button"
            aria-label="Open sidebar"
            onClick={() => setSidebarOpen(true)}
          >
            ☰
          </button>
          <ModelPicker
            models={chat.models}
            value={chat.model}
            disabled={chat.streaming}
            onChange={chat.chooseModel}
            onRefresh={chat.reloadModels}
          />
          <span className="topbar-title">{activeTitle}</span>
        </header>

        {chat.error && (
          <div className="banner" role="alert">
            <span>{chat.error}</span>
            <button className="icon-button" aria-label="Dismiss" onClick={chat.dismissError}>
              ✕
            </button>
          </div>
        )}

        {empty ? (
          <div className="empty">
            <h1>How can I help?</h1>
            <p>{chat.model ? `Chatting with ${chat.model} on your machine.` : "Pick a model."}</p>
          </div>
        ) : (
          <MessageList
            messages={chat.messages}
            streaming={chat.streaming}
            onRegenerate={chat.regenerate}
            onEdit={chat.edit}
          />
        )}

        <Composer
          key={chat.activeId ?? "new"}
          streaming={chat.streaming}
          disabled={!chat.model}
          onSend={chat.send}
          onStop={chat.stop}
        />
      </main>
    </div>
  );
}
