/**
 * KDS 声音提示工具 -- Web Audio API 合成
 *
 * 三种提示音，无外部音频文件依赖：
 *   playNewOrder()  -- 新订单提示（短促"叮"）
 *   playRush()      -- 催单告警（急促连续）
 *   playTimeout()   -- 超时告警（低沉警报）
 */

let _audioCtx: AudioContext | null = null;

function getAudioCtx(): AudioContext {
  if (!_audioCtx || _audioCtx.state === 'closed') {
    _audioCtx = new AudioContext();
  }
  // 浏览器安全策略：用户交互后才能播放
  if (_audioCtx.state === 'suspended') {
    _audioCtx.resume().catch(() => {});
  }
  return _audioCtx;
}

// ─── 内部：播放单个音调 ───

function playTone(
  frequency: number,
  duration: number,
  type: OscillatorType = 'sine',
  gainValue = 0.3,
  startTime = 0,
): void {
  const ctx = getAudioCtx();
  const osc = ctx.createOscillator();
  const gain = ctx.createGain();

  osc.type = type;
  osc.frequency.setValueAtTime(frequency, ctx.currentTime + startTime);

  gain.gain.setValueAtTime(gainValue, ctx.currentTime + startTime);
  gain.gain.exponentialRampToValueAtTime(
    0.001,
    ctx.currentTime + startTime + duration,
  );

  osc.connect(gain);
  gain.connect(ctx.destination);

  osc.start(ctx.currentTime + startTime);
  osc.stop(ctx.currentTime + startTime + duration);
}

// ─── 公开 API ───

/**
 * 新订单提示音 -- 短促清脆的"叮"
 * 两个递升音调，明亮友好
 */
export function playNewOrder(): void {
  try {
    playTone(880, 0.15, 'sine', 0.25, 0);
    playTone(1320, 0.2, 'sine', 0.2, 0.12);
  } catch {
    // AudioContext 不可用时静默
  }
}

/**
 * 催单告警 -- 急促连续哔声
 * 三声短促高频音
 */
export function playRush(): void {
  try {
    playTone(1000, 0.1, 'square', 0.2, 0);
    playTone(1000, 0.1, 'square', 0.2, 0.15);
    playTone(1200, 0.15, 'square', 0.25, 0.3);
  } catch {
    // AudioContext 不可用时静默
  }
}

/**
 * 超时告警 -- 低沉持续警报
 * 两声低频长音，紧迫感
 */
export function playTimeout(): void {
  try {
    playTone(330, 0.4, 'sawtooth', 0.2, 0);
    playTone(260, 0.5, 'sawtooth', 0.25, 0.45);
  } catch {
    // AudioContext 不可用时静默
  }
}

/**
 * 预热 AudioContext -- 在用户首次触控时调用
 * 解决浏览器 autoplay 限制
 */
export function warmUpAudio(): void {
  try {
    const ctx = getAudioCtx();
    // 播放一个无声音来解锁
    const osc = ctx.createOscillator();
    const gain = ctx.createGain();
    gain.gain.setValueAtTime(0, ctx.currentTime);
    osc.connect(gain);
    gain.connect(ctx.destination);
    osc.start();
    osc.stop(ctx.currentTime + 0.01);
  } catch {
    // 静默
  }
}
