import { useCallback, useEffect, useRef, useState } from "react";
import type { KeyboardEvent, PointerEvent, RefObject } from "react";

interface ResizableBounds {
  /** The element the panel shares its axis with. */
  ref: RefObject<HTMLElement | null>;
  /** Px along that axis the sibling must keep. */
  reserve: number;
}

interface ResizableOptions {
  /** Size the panel starts at, in px. */
  initial: number;
  /** Smallest size the drag may reach, in px. */
  min: number;
  /** Design cap, in px. Omit for a panel bounded only by its container. */
  max?: number;
  /**
   * Ties the ceiling to the live container, so a panel cannot crowd out its
   * sibling on a narrow window. Measured after mount and on every resize —
   * the first render uses the design cap alone so the server and the client
   * agree, then the effect narrows it.
   */
  bounds?: ResizableBounds;
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
  bounds,
  axis,
  label,
  step = 16,
}: ResizableOptions) {
  const cap = max ?? Number.POSITIVE_INFINITY;
  const [size, setSize] = useState(initial);
  const [limit, setLimit] = useState(cap);
  const releaseRef = useRef<(() => void) | null>(null);

  const boundsRef = bounds?.ref;
  const reserve = bounds?.reserve ?? 0;

  useEffect(() => {
    if (!boundsRef) return;

    const measure = () => {
      const el = boundsRef.current;
      if (!el) return;
      const extent = axis === "x" ? el.clientWidth : el.clientHeight;
      // A hidden or not-yet-laid-out container measures 0. Believing it would
      // collapse the panel to its minimum and strand it there once the
      // container is shown again.
      if (extent === 0) return;
      const available = extent - reserve;
      // A container too small for the minimum still owes the panel its
      // minimum; letting the ceiling drop under it would invert the clamp.
      const next = Math.max(min, Math.min(cap, available));
      setLimit(next);
      setSize((current) => Math.min(current, next));
    };

    measure();
    window.addEventListener("resize", measure);
    return () => window.removeEventListener("resize", measure);
  }, [axis, boundsRef, cap, min, reserve]);

  const onPointerDown = useCallback(
    (e: PointerEvent<HTMLDivElement>) => {
      e.preventDefault();
      releaseRef.current?.();

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
          setSize(Math.min(Math.max(startSize + start - current, min), limit));
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
    [axis, limit, min, size]
  );

  const onKeyDown = useCallback(
    (e: KeyboardEvent<HTMLDivElement>) => {
      const grow = axis === "x" ? "ArrowLeft" : "ArrowUp";
      const shrink = axis === "x" ? "ArrowRight" : "ArrowDown";

      const target = (current: number) => {
        switch (e.key) {
          case grow:
            return current + step;
          case shrink:
            return current - step;
          case "Home":
            return min;
          case "End":
            return limit;
          default:
            return null;
        }
      };

      if (target(size) === null) return;
      e.preventDefault();
      setSize((current) =>
        Math.min(Math.max(target(current) as number, min), limit)
      );
    },
    [axis, limit, min, size, step]
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
      "aria-valuemax": Number.isFinite(limit) ? limit : undefined,
      onPointerDown,
      onKeyDown,
    },
  };
}

export type SeparatorProps = ReturnType<typeof useResizable>["separatorProps"];
