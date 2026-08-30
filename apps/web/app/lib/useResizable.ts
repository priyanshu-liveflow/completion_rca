import { useCallback, useEffect, useRef, useState } from "react";
import type { MouseEvent as ReactMouseEvent } from "react";

interface ResizableOptions {
  /** Size the panel starts at, in px. */
  initial: number;
  /** Smallest size the drag may reach, in px. */
  min: number;
  /**
   * Largest size the drag may reach, in px. Pass a function when the ceiling
   * depends on layout that is only known once the drag begins — the dock
   * derives its maximum from the live workspace height.
   */
  max: number | (() => number);
  /** "x" for a vertical divider, "y" for a horizontal one. */
  axis: "x" | "y";
}

/**
 * Drag-to-resize for a panel anchored to the right or bottom edge, so the
 * panel grows as the pointer travels toward the top-left. Every resizer in
 * the workspace is edge-anchored; a leading-edge panel would need its own
 * sign and is deliberately not guessed at here.
 *
 * The drag suppresses text selection while it runs and tears itself down on
 * unmount, so a pop-out closing mid-drag cannot leave listeners on window.
 */
export function useResizable({ initial, min, max, axis }: ResizableOptions) {
  const [size, setSize] = useState(initial);
  const releaseRef = useRef<(() => void) | null>(null);

  const onMouseDown = useCallback(
    (e: ReactMouseEvent<HTMLDivElement>) => {
      e.preventDefault();
      releaseRef.current?.();

      const ceiling = typeof max === "function" ? max() : max;
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
        "mousemove",
        (ev: globalThis.MouseEvent) => {
          const current = axis === "x" ? ev.clientX : ev.clientY;
          setSize(Math.min(Math.max(startSize + start - current, min), ceiling));
        },
        { signal: controller.signal }
      );
      window.addEventListener("mouseup", release, {
        signal: controller.signal,
      });
    },
    [axis, max, min, size]
  );

  useEffect(() => () => releaseRef.current?.(), []);

  return { size, onMouseDown };
}
