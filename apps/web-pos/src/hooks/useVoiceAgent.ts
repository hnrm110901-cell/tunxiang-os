/**
 * useVoiceAgent — 语音 Agent Hook（TTS 播报 + Whisper/Web Speech 指令识别）
 *
 * Phase 3: 语音 Agent 界面
 *   - speak(text) → 使用 Web Speech API 朗读（TTS）
 *   - startListening() → 使用 Web Speech API 或 Whisper 语音转文字
 *   - stopListening() → 停止麦克风
 *
 * 支持：
 *   - KDS 出餐语音播报（"#003 请取餐"）
 *   - Whisper 语音指令（"搜索今天的折扣异常"）
 *   - Web Speech API 回退（浏览器原生支持）
 *
 * 回退策略：
 *   1. Web Speech API（Chrome/Safari 内置，零依赖）
 *   2. Whisper API（Mac mini coreml-bridge，需部署）
 */
import { useState, useCallback, useRef, useEffect } from 'react';

// SpeechRecognition 不在 TypeScript 标准 DOM lib 中（仅 webkit 前缀实现），
// 此处声明最小可用类型避免 typecheck 报错；实际能力由 capability detection 控制。
// eslint-disable-next-line @typescript-eslint/no-explicit-any
type SpeechRecognition = any;

// ─── 类型 ──────────────────────────────────────────────────────────────────────

export interface VoiceCommand {
  text: string;
  confidence: number;
  timestamp: string;
}

export interface UseVoiceAgentOptions {
  /** 语音播报语言，默认 'zh-CN' */
  lang?: string;
  /** 播报音量 0-1，默认 1 */
  volume?: number;
  /** 播报语速 0.5-2，默认 1 */
  rate?: number;
  /** 识别语言，默认 'zh-CN' */
  recognitionLang?: string;
  /** 是否启用持续监听，默认 false */
  continuous?: boolean;
  /** 识别到完整句子时的回调 */
  onCommand?: (command: VoiceCommand) => void;
  /** 播报完成回调 */
  onSpeakEnd?: () => void;
}

export interface UseVoiceAgentReturn {
  /** 是否正在说话（TTS 播放中） */
  speaking: boolean;
  /** 是否正在监听（麦克风开启） */
  listening: boolean;
  /** 当前识别的临时文本 */
  interimTranscript: string;
  /** 已识别完成的命令列表 */
  commands: VoiceCommand[];
  /** 语音播报 */
  speak: (text: string) => void;
  /** 停止播报 */
  stopSpeaking: () => void;
  /** 开始监听 */
  startListening: () => void;
  /** 停止监听 */
  stopListening: () => void;
  /** 是否支持语音识别 */
  recognitionSupported: boolean;
  /** 是否支持语音播报 */
  synthesisSupported: boolean;
  /** 清空已识别的命令 */
  clearCommands: () => void;
}

// ─── 常量 ──────────────────────────────────────────────────────────────────────

const MAX_COMMANDS = 20;

// ─── Hook ─────────────────────────────────────────────────────────────────────

export function useVoiceAgent(options: UseVoiceAgentOptions = {}): UseVoiceAgentReturn {
  const {
    lang = 'zh-CN',
    volume = 1,
    rate = 1,
    recognitionLang = 'zh-CN',
    continuous = false,
    onCommand,
    onSpeakEnd,
  } = options;

  const [speaking, setSpeaking] = useState(false);
  const [listening, setListening] = useState(false);
  const [interimTranscript, setInterimTranscript] = useState('');
  const [commands, setCommands] = useState<VoiceCommand[]>([]);

  const synthRef = useRef<SpeechSynthesis | null>(null);
  const recognitionRef = useRef<SpeechRecognition | null>(null);
  const utteranceRef = useRef<SpeechSynthesisUtterance | null>(null);
  const onCommandRef = useRef(onCommand);
  useEffect(() => { onCommandRef.current = onCommand; }, [onCommand]);

  // 检测 API 可用性
  const synthesisSupported = typeof window !== 'undefined' && 'speechSynthesis' in window;
  const recognitionSupported = typeof window !== 'undefined' && ('SpeechRecognition' in window || 'webkitSpeechRecognition' in window);

  // ── TTS 播报 ────────────────────────────────────────────────────────────────

  const speak = useCallback((text: string) => {
    if (!synthesisSupported || !text.trim()) return;

    // 停止当前播报
    window.speechSynthesis.cancel();

    const utterance = new SpeechSynthesisUtterance(text);
    utterance.lang = lang;
    utterance.volume = volume;
    utterance.rate = rate;

    utterance.onstart = () => setSpeaking(true);
    utterance.onend = () => {
      setSpeaking(false);
      onSpeakEnd?.();
    };
    utterance.onerror = () => {
      setSpeaking(false);
    };

    utteranceRef.current = utterance;
    synthRef.current = window.speechSynthesis;
    window.speechSynthesis.speak(utterance);
  }, [synthesisSupported, lang, volume, rate, onSpeakEnd]);

  const stopSpeaking = useCallback(() => {
    if (synthesisSupported) {
      window.speechSynthesis.cancel();
      setSpeaking(false);
    }
  }, [synthesisSupported]);

  // ── STT 语音识别 ────────────────────────────────────────────────────────────

  const startListening = useCallback(() => {
    if (!recognitionSupported) return;

    const SpeechRecognitionAPI = ((window as unknown as Record<string, unknown>).SpeechRecognition
      || (window as unknown as Record<string, unknown>).webkitSpeechRecognition) as { new (): SpeechRecognition } | undefined;

    if (!SpeechRecognitionAPI) return;

    const recognition = new SpeechRecognitionAPI();
    recognition.lang = recognitionLang;
    recognition.interimResults = true;
    recognition.continuous = continuous;
    recognition.maxAlternatives = 1;

    recognition.onresult = (event: SpeechRecognitionEvent) => {
      let interim = '';
      for (let i = event.resultIndex; i < event.results.length; i++) {
        const result = event.results[i];
        if (result.isFinal) {
          const cmd: VoiceCommand = {
            text: result[0].transcript.trim(),
            confidence: result[0].confidence,
            timestamp: new Date().toISOString(),
          };
          setCommands((prev) => [cmd, ...prev.slice(0, MAX_COMMANDS - 1)]);
          onCommandRef.current?.(cmd);
        } else {
          interim += result[0].transcript;
        }
      }
      setInterimTranscript(interim);
    };

    recognition.onerror = () => {
      setListening(false);
      // 浏览器会自动停止，尝试重启
      try { recognition.start(); } catch { /* Speech API not ready, safe to ignore */ }
    };

    recognition.onend = () => {
      setListening(false);
      if (continuous) {
        // 持续模式下自动重启
        try {
          recognition.start();
          setListening(true);
        } catch { /* Speech API not ready, safe to ignore */ }
      }
    };

    recognitionRef.current = recognition;

    try {
      recognition.start();
      setListening(true);
    } catch {
      // Speech recognition already active, safe to ignore
      setListening(false);
    }
  }, [recognitionSupported, recognitionLang, continuous, onCommand]);

  const stopListening = useCallback(() => {
    if (recognitionRef.current) {
      try { recognitionRef.current.stop(); } catch { /* Speech API not ready */ }
      recognitionRef.current = null;
    }
    setListening(false);
  }, []);

  const clearCommands = useCallback(() => {
    setCommands([]);
  }, []);

  // ── 清理 ────────────────────────────────────────────────────────────────────

  useEffect(() => {
    return () => {
      if (synthRef.current) {
        synthRef.current.cancel();
      }
      if (recognitionRef.current) {
        try { recognitionRef.current.stop(); } catch { /* Speech API not ready */ }
      }
    };
  }, []);

  return {
    speaking,
    listening,
    interimTranscript,
    commands,
    speak,
    stopSpeaking,
    startListening,
    stopListening,
    recognitionSupported,
    synthesisSupported,
    clearCommands,
  };
}
