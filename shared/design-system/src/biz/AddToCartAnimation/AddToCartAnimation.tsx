/**
 * AddToCartAnimation — 加购抛物线飞点动效
 *
 * 用法：
 *   const animRef = useRef<AddToCartAnimationHandle>(null);
 *   <AddToCartAnimation ref={animRef} cartRef={cartIconRef} />
 *   // 点击"加购"时：
 *   animRef.current?.trigger(buttonElement);
 */
import {
  forwardRef,
  useCallback,
  useEffect,
  useImperativeHandle,
  useRef,
  useState,
} from 'react';
import styles from './AddToCartAnimation.module.css';

/* ─── Types ─── */

interface FlyingDot {
  id: number;
  startX: number;
  startY: number;
  endX: number;
  endY: number;
}

export interface AddToCartAnimationProps {
  /** Ref to the cart icon element (animation target) */
  cartRef: React.RefObject<HTMLElement | null>;
  /** Called when a dot reaches the cart */
  onLand?: () => void;
}

export interface AddToCartAnimationHandle {
  /** Launch a flying dot from the center of `sourceElement` to the cart icon */
  trigger: (sourceElement: HTMLElement) => void;
}

/* ─── Constants ─── */

const DURATION = 400; // ms
let nextId = 0;

/* ─── Component ─── */

const AddToCartAnimation = forwardRef<
  AddToCartAnimationHandle,
  AddToCartAnimationProps
>(function AddToCartAnimation({ cartRef, onLand }, ref) {
  const [dots, setDots] = useState<FlyingDot[]>([]);
  const dotsRef = useRef(dots);
  dotsRef.current = dots;

  const removeDot = useCallback(
    (id: number) => {
      setDots((prev) => prev.filter((d) => d.id !== id));

      // Trigger cart shake
      const cartEl = cartRef.current;
      if (cartEl) {
        cartEl.classList.remove(styles.cartShake);
        // Force reflow to restart animation
        void cartEl.offsetWidth;
        cartEl.classList.add(styles.cartShake);
        const handleEnd = () => cartEl.classList.remove(styles.cartShake);
        cartEl.addEventListener('animationend', handleEnd, { once: true });
      }

      onLand?.();
    },
    [cartRef, onLand],
  );

  const trigger = useCallback(
    (sourceElement: HTMLElement) => {
      const cartEl = cartRef.current;
      if (!cartEl) return;

      const srcRect = sourceElement.getBoundingClientRect();
      const dstRect = cartEl.getBoundingClientRect();

      const dot: FlyingDot = {
        id: ++nextId,
        startX: srcRect.left + srcRect.width / 2,
        startY: srcRect.top + srcRect.height / 2,
        endX: dstRect.left + dstRect.width / 2,
        endY: dstRect.top + dstRect.height / 2,
      };

      setDots((prev) => [...prev, dot]);
    },
    [cartRef],
  );

  useImperativeHandle(ref, () => ({ trigger }), [trigger]);

  return (
    <>
      {dots.map((dot) => (
        <FlyingDotEl key={dot.id} dot={dot} onDone={() => removeDot(dot.id)} />
      ))}
    </>
  );
});

export default AddToCartAnimation;

/* ─── FlyingDotEl — individual animated dot ─── */

function FlyingDotEl({
  dot,
  onDone,
}: {
  dot: FlyingDot;
  onDone: () => void;
}) {
  const elRef = useRef<HTMLDivElement>(null);
  const rafRef = useRef<number>(0);
  const startTimeRef = useRef<number>(0);

  // Build the animation callback and start via useEffect (safe under strict mode)
  useEffect(() => {
    const animate = (time: number) => {
      if (!startTimeRef.current) startTimeRef.current = time;
      const elapsed = time - startTimeRef.current;
      const t = Math.min(elapsed / DURATION, 1);

      // Eased progress (ease-out cubic)
      const ease = 1 - Math.pow(1 - t, 3);

      // Linear interpolation for X
      const x = dot.startX + (dot.endX - dot.startX) * ease;

      // Parabolic arc for Y: add upward arc then fall
      const linearY = dot.startY + (dot.endY - dot.startY) * ease;
      // Peak height: 80px above the straight line midpoint
      const arcOffset = -80 * Math.sin(Math.PI * t);
      const y = linearY + arcOffset;

      // Opacity: fade out in last 20%
      const opacity = t > 0.8 ? 1 - (t - 0.8) / 0.2 : 1;

      // Scale: shrink to 0.5 at end
      const scale = 1 - 0.5 * t;

      const el = elRef.current;
      if (el) {
        el.style.left = `${x - 6}px`;
        el.style.top = `${y - 6}px`;
        el.style.opacity = String(opacity);
        el.style.transform = `scale(${scale})`;
      }

      if (t < 1) {
        rafRef.current = requestAnimationFrame(animate);
      } else {
        onDone();
      }
    };

    rafRef.current = requestAnimationFrame(animate);
    return () => cancelAnimationFrame(rafRef.current);
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  return <div ref={elRef} className={styles.dot} />;
}
