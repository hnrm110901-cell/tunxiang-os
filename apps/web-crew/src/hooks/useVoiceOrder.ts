/**
 * useVoiceOrder — 服务员端语音点单 Hook
 *
 * 识别流程：
 *   1. 优先使用浏览器内置 Web Speech API (SpeechRecognition)
 *      lang='zh-CN', continuous=false, interimResults=true
 *   2. 降级：录制 MediaRecorder blob → POST /api/v1/voice/transcribe
 *
 * NLU 流程：
 *   transcript 获得后 → POST /api/v1/voice/parse-order
 *   接口失败时用正则规则 fallback
 *
 * 使用方式：
 *   const {
 *     isListening, isProcessing, transcript, parsedOrder, error,
 *     startListening, stopListening, confirmOrder,
 *   } = useVoiceOrder({ tableNo, onOrderConfirmed });
 */

import { useCallback, useEffect, useRef, useState } from 'react';

// ─── 类型 ───────────────────────────────────────────────────────────────────

export interface ParsedOrderItem {
  dishName: string;
  quantity: number;
  note?: string;      // 如"少辣"、"不要香菜"
  confidence: number; // 0-1
}

export interface UseVoiceOrderOptions {
  tableNo: string;
  /** 可选：传入当前菜单名称列表，提高 NLU 精度 */
  menuContext?: string[];
  onOrderConfirmed: (items: ParsedOrderItem[]) => void;
}

export interface UseVoiceOrderReturn {
  isListening: boolean;
  isProcessing: boolean;
  transcript: string;
  parsedOrder: ParsedOrderItem[];
  error: string | null;
  startListening: () => void;
  stopListening: () => void;
  confirmOrder: () => void;
  clearOrder: () => void;
}

// ─── Web Speech API 类型补丁（浏览器全局，部分环境缺少声明）────────────────

interface SpeechRecognitionEvent extends Event {
  readonly resultIndex: number;
  readonly results: SpeechRecognitionResultList;
}

interface SpeechRecognitionErrorEvent extends Event {
  readonly error: string;
  readonly message: string;
}

interface SpeechRecognitionInstance extends EventTarget {
  lang: string;
  continuous: boolean;
  interimResults: boolean;
  onresult: ((e: SpeechRecognitionEvent) => void) | null;
  onerror: ((e: SpeechRecognitionErrorEvent) => void) | null;
  onend: (() => void) | null;
  start(): void;
  stop(): void;
  abort(): void;
}

type SpeechRecognitionConstructor = new () => SpeechRecognitionInstance;

// ─── 内部工具 ────────────────────────────────────────────────────────────────

function getSpeechRecognition(): SpeechRecognitionConstructor | null {
  const w = window as Record<string, unknown>;
  return (
    (w['SpeechRecognition'] as SpeechRecognitionConstructor | undefined) ??
    (w['webkitSpeechRecognition'] as SpeechRecognitionConstructor | undefined) ??
    null
  );
}

function getApiBase(): string {
  const w = window as Record<string, unknown>;
  return (w['__TX_API_BASE__'] as string | undefined) ?? '';
}

/**
 * 简单正则 fallback：当 NLU 接口不可用时，从文本中提取点单信息。
 * 匹配模式：
 *   - "来/要/加 [数字] [菜品名]"（如"来两个红烧肉"）
 *   - "[数字][个/份/杯/碗/盘] [菜品名]"（如"三份炒饭"）
 */
function fallbackParseOrder(text: string): ParsedOrderItem[] {
  const chineseNumMap: Record<string, number> = {
    一: 1, 二: 2, 两: 2, 三: 3, 四: 4, 五: 5,
    六: 6, 七: 7, 八: 8, 九: 9, 十: 10,
  };

  const toNumber = (s: string): number => {
    const n = parseInt(s, 10);
    if (!isNaN(n)) return n;
    return chineseNumMap[s] ?? 1;
  };

  const results: ParsedOrderItem[] = [];

  // 模式一：来/要/加 [数字] [菜品名]（菜品名 2-8 个汉字）
  const re1 = /[来要加]([一二两三四五六七八九十\d]+)\s*([^\s，。,！!？?]{2,8})/gu;
  let m: RegExpExecArray | null;
  while ((m = re1.exec(text)) !== null) {
    results.push({ dishName: m[2].trim(), quantity: toNumber(m[1]), confidence: 0.7 });
  }

  // 模式二：[数字][个/份/杯/碗/盘/串/斤/两] [菜品名]
  const re2 = /([一二两三四五六七八九十\d]+)\s*[个份杯碗盘串斤两]\s*([^\s，。,！!？?]{2,8})/gu;
  while ((m = re2.exec(text)) !== null) {
    // 避免与模式一重复
    const name = m[2].trim();
    if (!results.some(r => r.dishName === name)) {
      results.push({ dishName: name, quantity: toNumber(m[1]), confidence: 0.6 });
    }
  }

  return results;
}

// ─── Hook ────────────────────────────────────────────────────────────────────

export function useVoiceOrder({
  tableNo,
  menuContext,
  onOrderConfirmed,
}: UseVoiceOrderOptions): UseVoiceOrderReturn {
  const [isListening, setIsListening] = useState(false);
  const [isProcessing, setIsProcessing] = useState(false);
  const [transcript, setTranscript] = useState('');
  const [parsedOrder, setParsedOrder] = useState<ParsedOrderItem[]>([]);
  const [error, setError] = useState<string | null>(null);

  // --- refs (不触发重渲染) ---
  const recognitionRef = useRef<SpeechRecognitionInstance | null>(null);
  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const audioChunksRef = useRef<Blob[]>([]);
  const mountedRef = useRef(true);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      recognitionRef.current?.abort();
      if (mediaRecorderRef.current?.state !== 'inactive') {
        mediaRecorderRef.current?.stop();
      }
    };
  }, []);

  // --- NLU 调用 ---
  const parseOrderText = useCallback(
    async (text: string): Promise<ParsedOrderItem[]> => {
      const base = getApiBase();
      if (!base && !window.location.hostname) return fallbackParseOrder(text);

      try {
        const res = await fetch(`${base}/api/v1/voice/parse-order`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            text,
            table_no: tableNo,
            ...(menuContext && menuContext.length > 0 ? { menu_context: menuContext } : {}),
          }),
        });
        if (!res.ok) throw new Error(`parse-order HTTP ${res.status}`);
        const json = (await res.json()) as { ok: boolean; data?: { items: ParsedOrderItem[] } };
        if (json.ok && json.data?.items && json.data.items.length > 0) {
          return json.data.items;
        }
        return fallbackParseOrder(text);
      } catch {
        // NLU 失败 → 规则 fallback
        return fallbackParseOrder(text);
      }
    },
    [tableNo, menuContext],
  );

  // --- 处理最终 transcript ---
  const handleTranscript = useCallback(
    async (text: string) => {
      if (!mountedRef.current || !text.trim()) return;
      setTranscript(text);
      setIsProcessing(true);
      setError(null);
      try {
        const items = await parseOrderText(text);
        if (mountedRef.current) setParsedOrder(items);
      } catch {
        if (mountedRef.current) setError('解析点单失败，请重试');
      } finally {
        if (mountedRef.current) setIsProcessing(false);
      }
    },
    [parseOrderText],
  );

  // --- STT via mac-station（fallback）---
  const transcribeBlob = useCallback(
    async (blob: Blob): Promise<void> => {
      const base = getApiBase();
      try {
        const arrayBuffer = await blob.arrayBuffer();
        const base64 = btoa(
          String.fromCharCode(...new Uint8Array(arrayBuffer)),
        );
        const res = await fetch(`${base}/api/v1/voice/transcribe`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ audio_base64: base64, format: 'webm' }),
        });
        if (!res.ok) throw new Error(`transcribe HTTP ${res.status}`);
        const json = (await res.json()) as { ok: boolean; data?: { text: string } };
        const text = json.data?.text ?? '';
        if (text) await handleTranscript(text);
        else if (mountedRef.current) setError('未识别到语音，请重试');
      } catch {
        if (mountedRef.current) setError('语音上传失败，请检查网络');
      }
    },
    [handleTranscript],
  );

  // --- Web Speech API 路径 ---
  const startWithSpeechRecognition = useCallback(
    (SpeechRecognition: SpeechRecognitionConstructor): void => {
      const recognition = new SpeechRecognition();
      recognition.lang = 'zh-CN';
      recognition.continuous = false;
      recognition.interimResults = true;
      recognitionRef.current = recognition;

      let finalText = '';

      recognition.onresult = (e: SpeechRecognitionEvent) => {
        if (!mountedRef.current) return;
        let interim = '';
        for (let i = e.resultIndex; i < e.results.length; i++) {
          const result = e.results[i];
          if (result.isFinal) {
            finalText += result[0].transcript;
          } else {
            interim += result[0].transcript;
          }
        }
        // 实时展示中间结果
        setTranscript(finalText + interim);
      };

      recognition.onerror = (e: SpeechRecognitionErrorEvent) => {
        if (!mountedRef.current) return;
        setIsListening(false);
        if (e.error !== 'no-speech') {
          setError(`语音识别错误：${e.error}`);
        }
      };

      recognition.onend = () => {
        if (!mountedRef.current) return;
        setIsListening(false);
        if (finalText.trim()) {
          void handleTranscript(finalText.trim());
        } else if (mountedRef.current) {
          setError('未识别到语音，请重试');
        }
      };

      recognition.start();
      setIsListening(true);
      setError(null);
    },
    [handleTranscript],
  );

  // --- MediaRecorder 路径 ---
  const startWithMediaRecorder = useCallback(async (): Promise<void> => {
    let stream: MediaStream;
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    } catch {
      if (mountedRef.current) {
        setError('无法访问麦克风，请检查权限设置');
      }
      return;
    }

    const recorder = new MediaRecorder(stream, { mimeType: 'audio/webm' });
    audioChunksRef.current = [];
    mediaRecorderRef.current = recorder;

    recorder.ondataavailable = (e) => {
      if (e.data.size > 0) audioChunksRef.current.push(e.data);
    };

    recorder.onstop = () => {
      stream.getTracks().forEach(t => t.stop());
      if (!mountedRef.current) return;
      setIsListening(false);
      const blob = new Blob(audioChunksRef.current, { type: 'audio/webm' });
      void transcribeBlob(blob);
    };

    recorder.start();
    setIsListening(true);
    setError(null);
  }, [transcribeBlob]);

  // --- 公开接口 ---

  const startListening = useCallback((): void => {
    if (isListening || isProcessing) return;
    setTranscript('');
    setParsedOrder([]);
    setError(null);

    const SpeechRecognition = getSpeechRecognition();
    if (SpeechRecognition) {
      startWithSpeechRecognition(SpeechRecognition);
    } else {
      void startWithMediaRecorder();
    }
  }, [isListening, isProcessing, startWithSpeechRecognition, startWithMediaRecorder]);

  const stopListening = useCallback((): void => {
    if (recognitionRef.current) {
      recognitionRef.current.stop();
    }
    if (mediaRecorderRef.current?.state === 'recording') {
      mediaRecorderRef.current.stop();
    }
    setIsListening(false);
  }, []);

  const confirmOrder = useCallback((): void => {
    if (parsedOrder.length > 0) {
      onOrderConfirmed(parsedOrder);
    }
  }, [parsedOrder, onOrderConfirmed]);

  const clearOrder = useCallback((): void => {
    setTranscript('');
    setParsedOrder([]);
    setError(null);
  }, []);

  return {
    isListening,
    isProcessing,
    transcript,
    parsedOrder,
    error,
    startListening,
    stopListening,
    confirmOrder,
    clearOrder,
  };
}
