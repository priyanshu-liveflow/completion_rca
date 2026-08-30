import { act, fireEvent, renderHook } from "@testing-library/react";
import type { MouseEvent } from "react";
import { describe, expect, it, vi } from "vitest";
import { useResizable } from "./useResizable";

const press = (clientX: number, clientY: number) =>
  ({
    preventDefault: vi.fn(),
    clientX,
    clientY,
  }) as unknown as MouseEvent<HTMLDivElement>;

const rail = { initial: 270, min: 220, max: 520, axis: "x" } as const;

describe("useResizable", () => {
  it("starts at the initial size", () => {
    const { result } = renderHook(() => useResizable(rail));

    expect(result.current.size).toBe(270);
  });

  it("grows as the pointer moves toward the anchored edge", () => {
    const { result } = renderHook(() => useResizable(rail));

    act(() => result.current.onMouseDown(press(900, 0)));
    act(() => {
      fireEvent.mouseMove(window, { clientX: 850 });
    });

    expect(result.current.size).toBe(320);
  });

  it("shrinks as the pointer moves away from the anchored edge", () => {
    const { result } = renderHook(() => useResizable(rail));

    act(() => result.current.onMouseDown(press(900, 0)));
    act(() => {
      fireEvent.mouseMove(window, { clientX: 930 });
    });

    expect(result.current.size).toBe(240);
  });

  it("clamps at the maximum", () => {
    const { result } = renderHook(() => useResizable(rail));

    act(() => result.current.onMouseDown(press(900, 0)));
    act(() => {
      fireEvent.mouseMove(window, { clientX: 100 });
    });

    expect(result.current.size).toBe(520);
  });

  it("clamps at the minimum", () => {
    const { result } = renderHook(() => useResizable(rail));

    act(() => result.current.onMouseDown(press(900, 0)));
    act(() => {
      fireEvent.mouseMove(window, { clientX: 1800 });
    });

    expect(result.current.size).toBe(220);
  });

  it("tracks the y axis when asked", () => {
    const { result } = renderHook(() =>
      useResizable({ initial: 360, min: 120, max: 800, axis: "y" })
    );

    act(() => result.current.onMouseDown(press(0, 500)));
    act(() => {
      fireEvent.mouseMove(window, { clientY: 440 });
    });

    expect(result.current.size).toBe(420);
  });

  it("resolves a dynamic maximum at the start of each drag", () => {
    let ceiling = 400;
    const { result } = renderHook(() =>
      useResizable({ initial: 270, min: 220, max: () => ceiling, axis: "x" })
    );

    act(() => result.current.onMouseDown(press(900, 0)));
    act(() => {
      fireEvent.mouseMove(window, { clientX: 100 });
      fireEvent.mouseUp(window);
    });
    expect(result.current.size).toBe(400);

    ceiling = 300;
    act(() => result.current.onMouseDown(press(900, 0)));
    act(() => {
      fireEvent.mouseMove(window, { clientX: 100 });
    });
    expect(result.current.size).toBe(300);
  });

  it("suppresses text selection for the duration of the drag", () => {
    const { result } = renderHook(() => useResizable(rail));

    act(() => result.current.onMouseDown(press(900, 0)));
    expect(document.body.style.userSelect).toBe("none");

    act(() => {
      fireEvent.mouseUp(window);
    });
    expect(document.body.style.userSelect).toBe("");
  });

  it("releases the drag when the component unmounts mid-drag", () => {
    const { result, unmount } = renderHook(() => useResizable(rail));

    act(() => result.current.onMouseDown(press(900, 0)));
    expect(document.body.style.userSelect).toBe("none");

    unmount();

    expect(document.body.style.userSelect).toBe("");
    expect(() => fireEvent.mouseMove(window, { clientX: 100 })).not.toThrow();
  });
});
