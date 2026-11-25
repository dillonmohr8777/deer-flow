import { useParams, useSearchParams } from "next/navigation";
import { useEffect, useMemo, useRef } from "react";
import { toast } from "sonner";

import { usePromptInputController } from "@/components/ai-elements/prompt-input";
import { parsePrefillPrompt } from "@/components/workspace/control-panel/control-panel-data";
import { useI18n } from "@/core/i18n/hooks";

function focusTextareaAtEnd(expectedLength: number) {
  const textarea = document.querySelector("textarea");
  if (!textarea) {
    return;
  }
  textarea.focus();
  const end = Math.max(textarea.value.length, expectedLength);
  textarea.selectionStart = end;
  textarea.selectionEnd = end;
}

/**
 * Hook to determine if the chat is in a specific mode based on URL parameters,
 * and to apply or offer the requested prefill prompt without clobbering an
 * existing unsent composer draft.
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

  const currentValue = promptInputController.textInput.value;
  const handledValueRef = useRef<string | undefined>(undefined);
  const offeredValueRef = useRef<string | undefined>(undefined);
  const currentValueRef = useRef(currentValue);
  currentValueRef.current = currentValue;
  const setInputRef = useRef(promptInputController.textInput.setInput);
  setInputRef.current = promptInputController.textInput.setInput;

  useEffect(() => {
    if (!inputInitialValue) {
      offeredValueRef.current = undefined;
      return;
    }
    if (handledValueRef.current === inputInitialValue) {
      return;
    }
    const timer = setTimeout(() => {
      const textarea = document.querySelector("textarea");
      const existing = (
        currentValueRef.current.length > 0
          ? currentValueRef.current
          : (textarea?.value ?? "")
      ).trim();
      if (existing === inputInitialValue.trim()) {
        handledValueRef.current = inputInitialValue;
        offeredValueRef.current = undefined;
        return;
      }
      if (existing.length === 0) {
        handledValueRef.current = inputInitialValue;
        offeredValueRef.current = undefined;
        setInputRef.current(inputInitialValue);
        focusTextareaAtEnd(inputInitialValue.length);
        return;
      }
      if (offeredValueRef.current === inputInitialValue) {
        return;
      }
      offeredValueRef.current = inputInitialValue;
      toast("Selected workflow prompt is ready", {
        description:
          "You already have an unsent draft in the composer. Replace it with this workflow prompt or keep your draft.",
        action: {
          label: "Use workflow prompt",
          onClick: () => {
            handledValueRef.current = inputInitialValue;
            offeredValueRef.current = undefined;
            setInputRef.current(inputInitialValue);
            focusTextareaAtEnd(inputInitialValue.length);
          },
        },
        cancel: {
          label: "Keep draft",
          onClick: () => {
            handledValueRef.current = inputInitialValue;
            offeredValueRef.current = undefined;
          },
        },
      });
    }, 100);
    return () => clearTimeout(timer);
  }, [inputInitialValue, currentValue]);
}
