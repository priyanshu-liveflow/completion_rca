import { act, fireEvent, renderHook } from "@testing-library/react";
import type { KeyboardEvent, PointerEvent } from "react";
import { describe, expect, it, vi } from "vitest";
import { useResizable } from "./useResizable";

const press = (clientX: number, clientY: number) =>
  ({
    preventDefault: vi.fn(),
    clientX,
    clientY,
  }) as unknown as PointerEvent<HTMLDivElement>;

const rail = {
  initial: 270,
  min: 220,
  max: 520,
  axis: "x",
  label: "Resize rail",
} as const;

describe("useResizable", () => {
  it("starts at the initial size", () => {
    const { result } = renderHook(() => useResizable(rail));

    expect(result.current.size).toBe(270);
  });

  it("grows as the pointer moves toward the anchored edge", () => {
    const { result } = renderHook(() => useResizable(rail));

    act(() => result.current.separatorProps.onPointerDown(press(900, 0)));
    act(() => {
      fireEvent.pointerMove(window, { clientX: 850 });
    });

    expect(result.current.size).toBe(320);
  });

  it("shrinks as the pointer moves away from the anchored edge", () => {
    const { result } = renderHook(() => useResizable(rail));

    act(() => result.current.separatorProps.onPointerDown(press(900, 0)));
    act(() => {
      fireEvent.pointerMove(window, { clientX: 930 });
    });

    expect(result.current.size).toBe(240);
  });

  it("clamps at the maximum", () => {
    const { result } = renderHook(() => useResizable(rail));

    act(() => result.current.separatorProps.onPointerDown(press(900, 0)));
    act(() => {
      fireEvent.pointerMove(window, { clientX: 100 });
    });

    expect(result.current.size).toBe(520);
  });

  it("clamps at the minimum", () => {
    const { result } = renderHook(() => useResizable(rail));

    act(() => result.current.separatorProps.onPointerDown(press(900, 0)));
    act(() => {
      fireEvent.pointerMove(window, { clientX: 1800 });
    });

    expect(result.current.size).toBe(220);
  });

  it("tracks the y axis when asked", () => {
    const { result } = renderHook(() =>
      useResizable({
        initial: 360,
        min: 120,
        max: 800,
        axis: "y",
        label: "Resize dock",
      })
    );

    act(() => result.current.separatorProps.onPointerDown(press(0, 500)));
    act(() => {
      fireEvent.pointerMove(window, { clientY: 440 });
    });

    expect(result.current.size).toBe(420);
  });

  it("resolves a dynamic maximum at the start of each drag", () => {
    let ceiling = 400;
    const { result } = renderHook(() =>
      useResizable({
        initial: 270,
        min: 220,
        max: () => ceiling,
        axis: "x",
        label: "Resize rail",
      })
    );

    act(() => result.current.separatorProps.onPointerDown(press(900, 0)));
    act(() => {
      fireEvent.pointerMove(window, { clientX: 100 });
      fireEvent.pointerUp(window);
    });
    expect(result.current.size).toBe(400);

    ceiling = 300;
    act(() => result.current.separatorProps.onPointerDown(press(900, 0)));
    act(() => {
      fireEvent.pointerMove(window, { clientX: 100 });
    });
    expect(result.current.size).toBe(300);
  });

  it("suppresses text selection for the duration of the drag", () => {
    const { result } = renderHook(() => useResizable(rail));

    act(() => result.current.separatorProps.onPointerDown(press(900, 0)));
    expect(document.body.style.userSelect).toBe("none");

    act(() => {
      fireEvent.pointerUp(window);
    });
    expect(document.body.style.userSelect).toBe("");
  });

  it("releases the drag when the component unmounts mid-drag", () => {
    const { result, unmount } = renderHook(() => useResizable(rail));

    act(() => result.current.separatorProps.onPointerDown(press(900, 0)));
    expect(document.body.style.userSelect).toBe("none");

    unmount();

    expect(document.body.style.userSelect).toBe("");
    expect(() => fireEvent.pointerMove(window, { clientX: 100 })).not.toThrow();
  });
});

describe("useResizable separator semantics", () => {
  it("describes itself as a vertical separator on the x axis", () => {
    const { result } = renderHook(() => useResizable({ ...rail, label: "Resize rail" }));
    const props = result.current.separatorProps;

    expect(props.role).toBe("separator");
    expect(props.tabIndex).toBe(0);
    expect(props["aria-orientation"]).toBe("vertical");
    expect(props["aria-label"]).toBe("Resize rail");
  });

  it("describes itself as a horizontal separator on the y axis", () => {
    const { result } = renderHook(() =>
      useResizable({ initial: 360, min: 120, max: 800, axis: "y", label: "Resize dock" })
    );

    expect(result.current.separatorProps["aria-orientation"]).toBe("horizontal");
  });

  it("publishes its current and bounding values", () => {
    const { result } = renderHook(() => useResizable({ ...rail, label: "Resize rail" }));
    const props = result.current.separatorProps;

    expect(props["aria-valuenow"]).toBe(270);
    expect(props["aria-valuemin"]).toBe(220);
    expect(props["aria-valuemax"]).toBe(520);
  });

  it("omits a maximum it cannot know until the drag begins", () => {
    const { result } = renderHook(() =>
      useResizable({ initial: 270, min: 220, max: () => 400, axis: "x", label: "Resize rail" })
    );

    expect(result.current.separatorProps["aria-valuemax"]).toBeUndefined();
  });
});

describe("useResizable keyboard", () => {
  const keyed = (key: string) =>
    ({ key, preventDefault: vi.fn() }) as unknown as KeyboardEvent<HTMLDivElement>;

  it("grows when the arrow points toward the anchored edge", () => {
    const { result } = renderHook(() => useResizable({ ...rail, label: "Resize rail" }));

    act(() => result.current.separatorProps.onKeyDown(keyed("ArrowLeft")));

    expect(result.current.size).toBe(286);
  });

  it("shrinks when the arrow points away from the anchored edge", () => {
    const { result } = renderHook(() => useResizable({ ...rail, label: "Resize rail" }));

    act(() => result.current.separatorProps.onKeyDown(keyed("ArrowRight")));

    expect(result.current.size).toBe(254);
  });

  it("uses the vertical arrows on the y axis", () => {
    const { result } = renderHook(() =>
      useResizable({ initial: 360, min: 120, max: 800, axis: "y", label: "Resize dock" })
    );

    act(() => result.current.separatorProps.onKeyDown(keyed("ArrowUp")));
    expect(result.current.size).toBe(376);

    act(() => result.current.separatorProps.onKeyDown(keyed("ArrowDown")));
    expect(result.current.size).toBe(360);
  });

  it("jumps to the bounds with Home and End", () => {
    const { result } = renderHook(() => useResizable({ ...rail, label: "Resize rail" }));

    act(() => result.current.separatorProps.onKeyDown(keyed("End")));
    expect(result.current.size).toBe(520);

    act(() => result.current.separatorProps.onKeyDown(keyed("Home")));
    expect(result.current.size).toBe(220);
  });

  it("clamps keyboard steps at the bounds", () => {
    const { result } = renderHook(() =>
      useResizable({ initial: 224, min: 220, max: 520, axis: "x", label: "Resize rail" })
    );

    act(() => result.current.separatorProps.onKeyDown(keyed("ArrowRight")));

    expect(result.current.size).toBe(220);
  });

  it("ignores keys it does not handle", () => {
    const { result } = renderHook(() => useResizable({ ...rail, label: "Resize rail" }));

    act(() => result.current.separatorProps.onKeyDown(keyed("a")));

    expect(result.current.size).toBe(270);
  });
});
