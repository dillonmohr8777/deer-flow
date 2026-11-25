import { useParams, useSearchParams } from "next/navigation";
import { useEffect, useMemo, useRef } from "react";

import { usePromptInputController } from "@/components/ai-elements/prompt-input";
import { parsePrefillPrompt } from "@/components/workspace/control-panel/control-panel-data";
import { useI18n } from "@/core/i18n/hooks";

/**
 * Hook to determine if the chat is in a specific mode based on URL parameters, and to set an initial prompt input value accordingly.
 */
export function useSpecificChatMode() {
  const { t } = useI18n();
  const { thread_id: threadIdFromPath } = useParams<{ thread_id: string }>();
  const searchParams = useSearchParams();
  const promptInputController = usePromptInputController();
  const inputInitialValue = useMemo(() => {
    if (threadIdFromPath !== "new") {
      return undefined;
    }
    const promptParam = parsePrefillPrompt(searchParams.get("prompt"));
    if (promptParam) {
      return promptParam;
    }
    if (searchParams.get("mode") === "skill") {
      return t.inputBox.createSkillPrompt;
    }
    return undefined;
  }, [threadIdFromPath, searchParams, t.inputBox.createSkillPrompt]);
  const lastInitialValueRef = useRef<string | undefined>(undefined);
  const currentValueRef = useRef(promptInputController.textInput.value);
  currentValueRef.current = promptInputController.textInput.value;
  const setInputRef = useRef(promptInputController.textInput.setInput);
  setInputRef.current = promptInputController.textInput.setInput;
  useEffect(() => {
    if (
      inputInitialValue &&
      inputInitialValue !== lastInitialValueRef.current
    ) {
      lastInitialValueRef.current = inputInitialValue;
      const timer = setTimeout(() => {
        const textarea = document.querySelector("textarea");
        if (
          currentValueRef.current.trim().length > 0 ||
          (textarea?.value.trim().length ?? 0) > 0
        ) {
          return;
        }
        setInputRef.current(inputInitialValue);
        if (textarea) {
          textarea.focus();
          textarea.selectionStart = textarea.value.length;
          textarea.selectionEnd = textarea.value.length;
        }
      }, 100);
      return () => clearTimeout(timer);
    }
  }, [inputInitialValue]);
}
