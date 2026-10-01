"use client";

import { ArrowLeftIcon } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { toast } from "sonner";

import {
  PromptInput,
  PromptInputFooter,
  PromptInputSubmit,
  PromptInputTextarea,
} from "@/components/ai-elements/prompt-input";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { SidebarTrigger } from "@/components/ui/sidebar";
import { ArtifactsProvider } from "@/components/workspace/artifacts";
import { MessageList } from "@/components/workspace/messages";
import { ThreadContext } from "@/components/workspace/messages/context";
import { pageStyles, StatusTag } from "@/components/workspace/page-body";
import { useComposerOwnsBottomEdge } from "@/components/workspace/workspace-tab-bar";
import type { Agent } from "@/core/agents";
import {
  AgentNameCheckError,
  AgentsApiDisabledError,
  checkAgentName,
  getAgent,
} from "@/core/agents/api";
import { useI18n } from "@/core/i18n/hooks";
import {
  buildHumanInputResponseText,
  type HumanInputRequest,
  type HumanInputResponse,
} from "@/core/messages/human-input";
import { hasToolResult, useThreadStream } from "@/core/threads/hooks";
import { uuid } from "@/core/utils/uuid";
import { isIMEComposing } from "@/lib/ime";
import { cn } from "@/lib/utils";

type Step = "name" | "chat";
type SetupAgentStatus = "idle" | "requested" | "completed";

const NAME_RE = /^[A-Za-z0-9-]+$/;
const AGENT_READ_RETRY_DELAYS_MS = [200, 500, 1_000, 2_000];

function wait(ms: number) {
  return new Promise((resolve) => window.setTimeout(resolve, ms));
}

async function getAgentWithRetry(agentName: string) {
  for (const delay of [0, ...AGENT_READ_RETRY_DELAYS_MS]) {
    if (delay > 0) {
      await wait(delay);
    }

    try {
      return await getAgent(agentName);
    } catch {
      // Retry until the write settles or the attempts are exhausted.
    }
  }

  return null;
}

export default function NewAgentPage() {
  const { t } = useI18n();
  const router = useRouter();

  const [step, setStep] = useState<Step>("name");
  const [nameInput, setNameInput] = useState("");
  const [nameError, setNameError] = useState("");
  const [isCheckingName, setIsCheckingName] = useState(false);
  const [agentName, setAgentName] = useState("");
  const [agent, setAgent] = useState<Agent | null>(null);
  const [loadFailed, setLoadFailed] = useState(false);
  const [setupAgentStatus, setSetupAgentStatus] =
    useState<SetupAgentStatus>("idle");

  const threadId = useMemo(() => uuid(), []);

  const { thread, sendMessage } = useThreadStream({
    threadId: undefined,
    context: {
      mode: "flash",
      is_bootstrap: true,
    },
    onFinish(state) {
      if (agent || setupAgentStatus !== "requested") {
        return;
      }
      if (!agentName || !hasToolResult(state.messages, "setup_agent")) {
        setSetupAgentStatus("idle");
        return;
      }
      setSetupAgentStatus("completed");
      void getAgentWithRetry(agentName).then((fetched) => {
        if (fetched) {
          setAgent(fetched);
          return;
        }

        toast.error(t.agents.agentCreatedPendingRefresh);
        setLoadFailed(true);
      });
    },
  });
  // The composer owns the bottom edge in the chat step, as in any
  // conversation, so the phone tab bar steps aside.
  useComposerOwnsBottomEdge(step === "chat");

  const handleConfirmName = useCallback(async () => {
    const trimmed = nameInput.trim();
    if (!trimmed) return;
    if (!NAME_RE.test(trimmed)) {
      setNameError(t.agents.nameStepInvalidError);
      return;
    }

    setNameError("");
    setIsCheckingName(true);
    try {
      const result = await checkAgentName(trimmed);
      if (!result.available) {
        setNameError(t.agents.nameStepAlreadyExistsError);
        return;
      }
    } catch (err) {
      if (err instanceof AgentsApiDisabledError) {
        setNameError(t.agents.nameStepApiDisabledError);
      } else if (
        err instanceof AgentNameCheckError &&
        err.reason === "backend_unreachable"
      ) {
        setNameError(t.agents.nameStepNetworkError);
      } else if (
        err instanceof AgentNameCheckError &&
        err.reason === "request_failed"
      ) {
        // Surface the backend-provided detail (e.g. validation error) when
        // one is present, wrapped in a localised prefix so zh-CN users
        // don't see a bare English string next to the surrounding Chinese
        // UI. Falls back to the generic localised fallback when the backend
        // sent no detail — `err.message` is unreliable for this branch
        // because `checkAgentName` substitutes a generated fallback string
        // ("Failed to check agent name: ${statusText}") when `detail` is
        // missing, so testing `err.message` would always be truthy and the
        // generated fallback would leak through.
        setNameError(
          err.detail
            ? t.agents.nameStepCheckErrorWithDetail.replace(
                "{detail}",
                err.detail,
              )
            : t.agents.nameStepCheckError,
        );
      } else {
        setNameError(t.agents.nameStepCheckError);
      }
      return;
    } finally {
      setIsCheckingName(false);
    }

    setAgentName(trimmed);
    setStep("chat");
    await sendMessage(
      threadId,
      {
        text: t.agents.nameStepBootstrapMessage.replace("{name}", trimmed),
        files: [],
      },
      { agent_name: trimmed },
    );
  }, [
    nameInput,
    sendMessage,
    t.agents.nameStepAlreadyExistsError,
    t.agents.nameStepApiDisabledError,
    t.agents.nameStepNetworkError,
    t.agents.nameStepBootstrapMessage,
    t.agents.nameStepCheckError,
    t.agents.nameStepCheckErrorWithDetail,
    t.agents.nameStepInvalidError,
    threadId,
  ]);

  const handleNameKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Enter" && !isIMEComposing(e)) {
      e.preventDefault();
      void handleConfirmName();
    }
  };

  const handleChatSubmit = useCallback(
    async (text: string) => {
      const trimmed = text.trim();
      if (!trimmed || thread.isLoading) return;
      await sendMessage(
        threadId,
        { text: trimmed, files: [] },
        { agent_name: agentName },
      );
    },
    [agentName, sendMessage, thread.isLoading, threadId],
  );

  const handleSubmitHumanInput = useCallback(
    async (request: HumanInputRequest, response: HumanInputResponse) => {
      if (!agentName) {
        return false;
      }

      let sent = false;
      await sendMessage(
        threadId,
        {
          text: buildHumanInputResponseText(request, response),
          files: [],
        },
        { agent_name: agentName },
        {
          additionalKwargs: {
            hide_from_ui: true,
            human_input_response: response,
          },
          onSent: () => {
            sent = true;
          },
        },
      );
      return sent;
    },
    [agentName, sendMessage, threadId],
  );

  const handleSaveAgent = useCallback(async () => {
    if (
      !agentName ||
      agent ||
      thread.isLoading ||
      setupAgentStatus !== "idle"
    ) {
      return;
    }

    setSetupAgentStatus("requested");
    try {
      await sendMessage(
        threadId,
        { text: t.agents.saveCommandMessage, files: [] },
        { agent_name: agentName },
        { additionalKwargs: { hide_from_ui: true } },
      );
      toast.success(t.agents.saveRequested);
    } catch (error) {
      setSetupAgentStatus("idle");
      toast.error(error instanceof Error ? error.message : String(error));
    }
  }, [
    agent,
    agentName,
    sendMessage,
    setupAgentStatus,
    t.agents.saveCommandMessage,
    t.agents.saveRequested,
    thread.isLoading,
    threadId,
  ]);

  // Saved also when setup succeeded but the agent could not be read back
  // yet: the page then says so itself instead of leaving Save disabled.
  const saved = Boolean(agent) || loadFailed;
  const saveDisabled = saved || thread.isLoading || setupAgentStatus !== "idle";
  // Save is replaced by the Saved tag, so the focused button disappears
  // and focus would fall to the page. Hand it to the saved sheet instead,
  // only when focus was actually lost.
  const savedSheetRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!saved) return;
    const active = document.activeElement;
    if (!active || active === document.body)
      savedSheetRef.current?.focus({ preventScroll: true });
  }, [saved]);

  // The chat step heads itself with the agent being built (the name step
  // already chose it) and keeps Save, the page's one action, in the open:
  // it used to sit behind a "..." menu that a banner had to explain.
  const header = (
    <header className="flex shrink-0 items-center gap-1 border-b px-4 py-2 sm:gap-2 sm:py-3">
      <SidebarTrigger className="-ml-2 md:hidden" />
      <Button
        asChild
        variant="ghost"
        size="icon-sm"
        className="max-md:-ml-1 md:-ml-2"
      >
        <Link
          href="/workspace/agents"
          aria-label={t.agents.backToGallery}
          title={t.agents.backToGallery}
        >
          <ArrowLeftIcon className="h-4 w-4" />
        </Link>
      </Button>
      {/* The builder Momo again: the same new teammate the name step drew. */}
      <img
        src="/momentum/momos/builder.svg"
        alt=""
        aria-hidden="true"
        width={32}
        height={32}
        className="size-8 shrink-0"
      />
      <div className="min-w-0 flex-1 pl-1">
        <p className={cn(pageStyles.eyebrow, "leading-4")}>
          {t.agents.chatStepEyebrow}
        </p>
        <h1
          className="truncate text-sm leading-5 font-semibold"
          title={agentName}
        >
          {agentName}
        </h1>
      </div>
      {saved ? (
        <StatusTag tone="ok" className="shrink-0">
          {t.agents.chatStepSaved}
        </StatusTag>
      ) : (
        <Button
          size="sm"
          className="shrink-0 max-sm:h-11 max-sm:px-4"
          onClick={() => void handleSaveAgent()}
          disabled={saveDisabled}
        >
          {setupAgentStatus === "requested" ? t.agents.saving : t.agents.save}
        </Button>
      )}
    </header>
  );

  if (step === "name") {
    // The page heads itself like Agents and leads with the field at the top
    // of the frame, not centred: the field autofocuses, so on a phone the
    // keyboard is up from the first frame and a centred form sat under it.
    return (
      <div
        className={cn(
          "flex size-full flex-col overflow-y-auto",
          pageStyles.page,
        )}
      >
        <main className="mx-auto w-full max-w-2xl px-4 pt-3 pb-28 sm:px-8 sm:pt-6">
          <div className="-ml-2 flex items-center gap-1">
            <SidebarTrigger className="md:hidden" />
            <Button
              asChild
              variant="ghost"
              size="sm"
              className="text-muted-foreground max-sm:h-11"
            >
              <Link href="/workspace/agents">
                <ArrowLeftIcon className="h-4 w-4" />
                {t.agents.title}
              </Link>
            </Button>
          </div>
          <h1 className="mt-2">{t.agents.createPageTitle}</h1>
          <p className={cn(pageStyles.lede, "mt-1")}>
            {t.agents.createPageSubtitle}
          </p>

          <div
            className={cn(
              pageStyles.sheet,
              // A fresh sheet torn off the pad; the tear takes the top 24px.
              "paper-torn mt-6 space-y-4 border p-4 pt-8 sm:p-6 sm:pt-9",
            )}
          >
            <div className="flex items-start gap-4">
              {/* A new teammate: the builder Momo, decorative beside the label. */}
              <img
                src="/momentum/momos/builder.svg"
                alt=""
                aria-hidden="true"
                width={64}
                height={64}
                className="size-14 shrink-0 sm:size-16"
              />
              <div className="min-w-0 space-y-1 pt-1">
                <label
                  htmlFor="agent-name"
                  className="block text-base font-bold"
                >
                  {t.agents.nameStepTitle}
                </label>
                <p
                  id="agent-name-hint"
                  className="text-muted-foreground text-sm"
                >
                  {t.agents.nameStepHint}
                </p>
              </div>
            </div>

            <Input
              id="agent-name"
              autoFocus
              autoCapitalize="none"
              autoCorrect="off"
              spellCheck={false}
              aria-describedby={
                nameError
                  ? "agent-name-error agent-name-hint"
                  : "agent-name-hint"
              }
              aria-invalid={Boolean(nameError)}
              placeholder={t.agents.nameStepPlaceholder}
              value={nameInput}
              onChange={(e) => {
                setNameInput(e.target.value);
                setNameError("");
              }}
              onKeyDown={handleNameKeyDown}
              className={cn("max-sm:h-11", nameError && "border-destructive")}
            />
            {nameError ? (
              <p
                id="agent-name-error"
                role="alert"
                className="text-destructive text-sm"
              >
                {nameError}
              </p>
            ) : null}
            <Button
              className="w-full max-sm:h-11 sm:w-auto"
              onClick={() => void handleConfirmName()}
              disabled={!nameInput.trim() || isCheckingName}
            >
              {t.agents.nameStepContinue}
            </Button>
            <p className="text-muted-foreground border-border/50 border-t border-dashed pt-4 text-sm">
              {t.agents.nameStepNext}
            </p>
          </div>
        </main>
      </div>
    );
  }

  return (
    <ThreadContext.Provider value={{ thread }}>
      <ArtifactsProvider>
        <div className="flex size-full flex-col">
          {header}

          <main className="flex min-h-0 flex-1 flex-col">
            <div className="flex min-h-0 flex-1 justify-center">
              <MessageList
                className="size-full pt-6 sm:pt-10"
                threadId={threadId}
                thread={thread}
                onSubmitHumanInput={
                  agentName ? handleSubmitHumanInput : undefined
                }
              />
            </div>

            <div className="bg-background flex shrink-0 justify-center border-t px-4 pt-3 pb-[max(0.75rem,env(safe-area-inset-bottom))] sm:py-4">
              <div className="w-full max-w-(--container-width-md)">
                {saved ? (
                  // Saved: a cream-hi sheet that says what happened and
                  // offers the two ways on, not a centred check mark.
                  <div
                    ref={savedSheetRef}
                    tabIndex={-1}
                    role="status"
                    className={cn(
                      pageStyles.sheet,
                      "flex flex-col gap-4 border p-4 sm:flex-row sm:items-center sm:justify-between sm:p-5",
                    )}
                  >
                    {/* The header already says Saved; the sheet says where
                        the agent went and what to do with it. */}
                    <p className="min-w-0 text-sm font-semibold">
                      {agent
                        ? t.agents.agentCreated.replace("{name}", agentName)
                        : t.agents.agentCreatedPendingRefresh}
                    </p>
                    <div className="flex flex-col gap-2 sm:flex-row">
                      <Button
                        className="max-sm:h-11"
                        onClick={() =>
                          router.push(
                            `/workspace/agents/${agentName}/chats/new`,
                          )
                        }
                      >
                        {t.agents.startChatting}
                      </Button>
                      <Button
                        variant="outline"
                        className="max-sm:h-11"
                        onClick={() => router.push("/workspace/agents")}
                      >
                        {t.agents.backToGallery}
                      </Button>
                    </div>
                  </div>
                ) : (
                  <PromptInput
                    disabled={thread.isLoading}
                    onSubmit={({ text }) => void handleChatSubmit(text)}
                  >
                    <PromptInputTextarea
                      autoFocus
                      placeholder={t.agents.chatStepPlaceholder}
                      disabled={thread.isLoading}
                    />
                    <PromptInputFooter className="justify-end">
                      <PromptInputSubmit disabled={thread.isLoading} />
                    </PromptInputFooter>
                  </PromptInput>
                )}
              </div>
            </div>
          </main>
        </div>
      </ArtifactsProvider>
    </ThreadContext.Provider>
  );
}
