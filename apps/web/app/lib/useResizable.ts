import { useCallback, useEffect, useRef, useState } from "react";
import type { KeyboardEvent, PointerEvent } from "react";

interface ResizableOptions {
  /** Size the panel starts at, in px. */
  initial: number;
  /** Smallest size the drag may reach, in px. */
  min: number;
  /**
   * Largest size the drag may reach, in px. Pass a function when the ceiling
   * depends on layout that is only known once the drag begins — the dock
   * derives its maximum from the live workspace height. A function ceiling is
   * left out of aria-valuemax, which must not depend on a ref the server has
   * no way to read.
   */
  max: number | (() => number);
  /** "x" for a vertical divider, "y" for a horizontal one. */
  axis: "x" | "y";
  /** Announced to assistive tech, e.g. "Resize approval rail". */
  label: string;
  /** Px moved per arrow key press. */
  step?: number;
}

/**
 * Drag- and keyboard-resize for a panel anchored to the right or bottom edge,
 * so the panel grows as the divider travels toward the top-left. Every resizer
 * in the workspace is edge-anchored; a leading-edge panel would need its own
 * sign and is deliberately not guessed at here.
 *
 * Pointer events rather than mouse events, so touch and pen drag too. The drag
 * suppresses text selection while it runs and tears itself down on unmount, so
 * a pop-out closing mid-drag cannot leave listeners on window.
 */
export function useResizable({
  initial,
  min,
  max,
  axis,
  label,
  step = 16,
}: ResizableOptions) {
  const [size, setSize] = useState(initial);
  const releaseRef = useRef<(() => void) | null>(null);

  const ceilingOf = useCallback(
    () => (typeof max === "function" ? max() : max),
    [max]
  );

  const onPointerDown = useCallback(
    (e: PointerEvent<HTMLDivElement>) => {
      e.preventDefault();
      releaseRef.current?.();

      const ceiling = ceilingOf();
      const start = axis === "x" ? e.clientX : e.clientY;
      const startSize = size;
      const controller = new AbortController();

      const release = () => {
        releaseRef.current = null;
        document.body.style.userSelect = "";
        controller.abort();
      };
      releaseRef.current = release;
      document.body.style.userSelect = "none";

      window.addEventListener(
        "pointermove",
        (ev: globalThis.PointerEvent) => {
          const current = axis === "x" ? ev.clientX : ev.clientY;
          setSize(Math.min(Math.max(startSize + start - current, min), ceiling));
        },
        { signal: controller.signal }
      );
      window.addEventListener("pointerup", release, {
        signal: controller.signal,
      });
      window.addEventListener("pointercancel", release, {
        signal: controller.signal,
      });
    },
    [axis, ceilingOf, min, size]
  );

  const onKeyDown = useCallback(
    (e: KeyboardEvent<HTMLDivElement>) => {
      const grow = axis === "x" ? "ArrowLeft" : "ArrowUp";
      const shrink = axis === "x" ? "ArrowRight" : "ArrowDown";

      const next = (current: number) => {
        switch (e.key) {
          case grow:
            return current + step;
          case shrink:
            return current - step;
          case "Home":
            return min;
          case "End":
            return ceilingOf();
          default:
            return null;
        }
      };

      setSize((current) => {
        const target = next(current);
        if (target === null) return current;
        return Math.min(Math.max(target, min), ceilingOf());
      });

      if (next(size) !== null) e.preventDefault();
    },
    [axis, ceilingOf, min, size, step]
  );

  useEffect(() => () => releaseRef.current?.(), []);

  return {
    size,
    separatorProps: {
      role: "separator" as const,
      tabIndex: 0,
      "aria-label": label,
      "aria-orientation": (axis === "x" ? "vertical" : "horizontal") as
        | "vertical"
        | "horizontal",
      "aria-valuenow": size,
      "aria-valuemin": min,
      "aria-valuemax": typeof max === "number" ? max : undefined,
      onPointerDown,
      onKeyDown,
    },
  };
}

export type SeparatorProps = ReturnType<typeof useResizable>["separatorProps"];
