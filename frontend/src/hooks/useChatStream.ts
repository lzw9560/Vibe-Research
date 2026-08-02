/** useChatStream - AI 对话流式 hook */
import { useState, useCallback, useRef } from "react";
import { chatStream } from "@/lib/llm";
import type { ChatMsg } from "@/lib/llm";

interface UseChatStreamOptions {
  onMessage?: (content: string) => void;
  onError?: (error: string) => void;
}

export function useChatStream(options?: UseChatStreamOptions) {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const abortRef = useRef(false);

  const stream = useCallback(async (
    messages: ChatMsg[],
    conversationId: string,
    extraOptions?: Parameters<typeof chatStream>[2]
  ) => {
    setLoading(true);
    setError(null);
    abortRef.current = false;

    try {
      await chatStream(messages, conversationId, {
        ...extraOptions,
        onDelta: (delta) => {
          options?.onMessage?.(delta);
          extraOptions?.onDelta?.(delta);
        },
      });
    } catch (e) {
      const errMsg = e instanceof Error ? e.message : "聊天失败";
      setError(errMsg);
      options?.onError?.(errMsg);
    } finally {
      setLoading(false);
    }
  }, [options]);

  const stop = useCallback(() => {
    abortRef.current = true;
    setLoading(false);
  }, []);

  return { loading, error, stream, stop };
}
