import { AgentSidebar } from '../components/AgentSidebar.jsx';
import { ChatPanel } from '../components/ChatPanel.jsx';

export function WorkbenchPage({
  apiBase,
  status,
  agents,
  activeAgent,
  activeAgentId,
  setActiveAgentId,
  agentDetails,
  resources,
  capabilities,
  capabilityCandidates,
  capabilityBindings,
  diagnostics,
  runtimeStatus,
  packages,
  updateAgent,
  saveCapabilityBinding,
  saveCapabilityBindings,
  savePluginConfig,
  restartPluginInstance,
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
  return (
    <div className="workbench-page">
      <AgentSidebar
        agents={agents}
        activeAgentId={activeAgentId}
        setActiveAgentId={setActiveAgentId}
        agentDetails={agentDetails}
        resources={resources}
        capabilities={capabilities}
        capabilityCandidates={capabilityCandidates}
        capabilityBindings={capabilityBindings}
        diagnostics={diagnostics}
        runtimeStatus={runtimeStatus}
        packages={packages}
        updateAgent={updateAgent}
        saveCapabilityBinding={saveCapabilityBinding}
        saveCapabilityBindings={saveCapabilityBindings}
        savePluginConfig={savePluginConfig}
        restartPluginInstance={restartPluginInstance}
      />
      <ChatPanel
        apiBase={apiBase}
        status={status}
        activeAgent={activeAgent}
        agentDetails={agentDetails}
        resources={resources}
        capabilities={capabilities}
        diagnostics={diagnostics}
        runtimeStatus={runtimeStatus}
        sessions={sessions}
        activeSessionId={activeSessionId}
        sessionsLoading={sessionsLoading}
        createSession={createSession}
        selectSession={selectSession}
        deleteSession={deleteSession}
        messages={messages}
        isRunning={isRunning}
        sendMessage={sendMessage}
      />
    </div>
  );
}
