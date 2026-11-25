import { useParams, usePathname, useSearchParams } from "next/navigation";
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
  const pathname = usePathname();
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

  const routePromptKey = inputInitialValue
    ? `${pathname}::${threadIdFromPath}::${inputInitialValue}`
    : undefined;
  const currentValue = promptInputController.textInput.value;
  const handledKeyRef = useRef<string | undefined>(undefined);
  const offeredKeyRef = useRef<string | undefined>(undefined);
  const activeOfferTokenRef = useRef(0);
  const activeToastIdRef = useRef<string | number | undefined>(undefined);
  const currentValueRef = useRef(currentValue);
  currentValueRef.current = currentValue;
  const setInputRef = useRef(promptInputController.textInput.setInput);
  setInputRef.current = promptInputController.textInput.setInput;

  // Invalidate any pending replacement toast whenever the route or requested
  // prompt changes, and clear handled state when leaving a prefill route so
  // returning to the same workflow later can prefill again.
  useEffect(() => {
    activeOfferTokenRef.current += 1;
    if (activeToastIdRef.current !== undefined) {
      toast.dismiss(activeToastIdRef.current);
      activeToastIdRef.current = undefined;
    }
    if (!routePromptKey) {
      handledKeyRef.current = undefined;
      offeredKeyRef.current = undefined;
    }
    return () => {
      activeOfferTokenRef.current += 1;
      if (activeToastIdRef.current !== undefined) {
        toast.dismiss(activeToastIdRef.current);
        activeToastIdRef.current = undefined;
      }
    };
  }, [pathname, threadIdFromPath, routePromptKey]);

  useEffect(() => {
    if (!inputInitialValue || !routePromptKey) {
      return;
    }
    if (handledKeyRef.current === routePromptKey) {
      return;
    }
    const offerToken = activeOfferTokenRef.current;
    const timer = setTimeout(() => {
      if (activeOfferTokenRef.current !== offerToken) {
        return;
      }
      const textarea = document.querySelector("textarea");
      const existing = (
        currentValueRef.current.length > 0
          ? currentValueRef.current
          : (textarea?.value ?? "")
      ).trim();
      if (existing === inputInitialValue.trim()) {
        handledKeyRef.current = routePromptKey;
        offeredKeyRef.current = undefined;
        return;
      }
      if (existing.length === 0) {
        handledKeyRef.current = routePromptKey;
        offeredKeyRef.current = undefined;
        setInputRef.current(inputInitialValue);
        focusTextareaAtEnd(inputInitialValue.length);
        return;
      }
      if (offeredKeyRef.current === routePromptKey) {
        return;
      }
      offeredKeyRef.current = routePromptKey;
      activeToastIdRef.current = toast("Selected workflow prompt is ready", {
        description:
          "You already have an unsent draft in the composer. Replace it with this workflow prompt or keep your draft.",
        action: {
          label: "Use workflow prompt",
          onClick: () => {
            if (activeOfferTokenRef.current !== offerToken) {
              return;
            }
            handledKeyRef.current = routePromptKey;
            offeredKeyRef.current = undefined;
            activeToastIdRef.current = undefined;
            setInputRef.current(inputInitialValue);
            focusTextareaAtEnd(inputInitialValue.length);
          },
        },
        cancel: {
          label: "Keep draft",
          onClick: () => {
            if (activeOfferTokenRef.current !== offerToken) {
              return;
            }
            handledKeyRef.current = routePromptKey;
            offeredKeyRef.current = undefined;
            activeToastIdRef.current = undefined;
          },
        },
      });
    }, 100);
    return () => clearTimeout(timer);
  }, [inputInitialValue, routePromptKey, currentValue]);
}
