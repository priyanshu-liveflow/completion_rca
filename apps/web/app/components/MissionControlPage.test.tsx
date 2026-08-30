import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import MissionControlPage from "./MissionControlPage";
import { MissionProvider } from "./MissionProvider";

describe("mission approval gate", () => {
  afterEach(() => {
    vi.useRealTimers();
  });

  it("keeps approval disabled before red-to-green evidence has been observed", () => {
    render(
      <MissionProvider>
        <MissionControlPage />
      </MissionProvider>
    );

    expect(
      screen.getByRole("button", { name: "Approve verified PR" })
    ).toBeDisabled();
  });

  it("stays locked at red and unlocks after the later green fixture event", () => {
    vi.useFakeTimers();
    render(
      <MissionProvider>
        <MissionControlPage />
      </MissionProvider>
    );
    const approveButton = screen.getByRole("button", {
      name: "Approve verified PR",
    });

    act(() => {
      vi.advanceTimersByTime(2280);
    });

    expect(approveButton).toBeDisabled();
    expect(
      screen.getByText(
        "Locked while selected tests are red; waiting for green verification."
      )
    ).toBeInTheDocument();

    act(() => {
      vi.advanceTimersByTime(980);
    });

    expect(approveButton).toBeEnabled();
    expect(
      screen.getByText("The PR tool stayed locked while tests were red.")
    ).toBeInTheDocument();
  });
});

describe("MissionMap", () => {
  it("renders six proof nodes as buttons with five interleaved arrows", () => {
    render(
      <MissionProvider>
        <MissionControlPage />
      </MissionProvider>
    );

    const buttons = screen.getAllByRole("button").filter(
      (el) => el.getAttribute("aria-pressed") !== null
    );
    expect(buttons).toHaveLength(6);

    const arrows = document.querySelectorAll(`[aria-hidden="true"]`);
    expect(arrows.length).toBeGreaterThanOrEqual(5);
  });

  it("sets aria-pressed when a node is selected", () => {
    render(
      <MissionProvider>
        <MissionControlPage />
      </MissionProvider>
    );

    const buttons = screen.getAllByRole("button").filter(
      (el) => el.getAttribute("aria-pressed") !== null
    );
    const first = buttons[0];
    expect(first).toHaveAttribute("aria-pressed", "false");
    fireEvent.click(first);
    expect(first).toHaveAttribute("aria-pressed", "true");
  });

  it("selects and deselects a node with Enter", () => {
    render(
      <MissionProvider>
        <MissionControlPage />
      </MissionProvider>
    );

    const buttons = screen.getAllByRole("button").filter(
      (el) => el.getAttribute("aria-pressed") !== null
    );
    const first = buttons[0];
    fireEvent.keyDown(first, { key: "Enter" });
    expect(first).toHaveAttribute("aria-pressed", "true");
    fireEvent.keyDown(first, { key: "Enter" });
    expect(first).toHaveAttribute("aria-pressed", "false");
  });

  it("selects a focused node with Space", () => {
    render(
      <MissionProvider>
        <MissionControlPage />
      </MissionProvider>
    );

    const buttons = screen.getAllByRole("button").filter(
      (el) => el.getAttribute("aria-pressed") !== null
    );
    const first = buttons[0];
    fireEvent.keyDown(first, { key: " " });
    expect(first).toHaveAttribute("aria-pressed", "true");
  });
});

describe("RuntimeIndicator", () => {
  it("shows fixture copy and no live/connected claim", () => {
    render(
      <MissionProvider>
        <MissionControlPage />
      </MissionProvider>
    );

    expect(screen.getByText("Fixture replay")).toBeInTheDocument();
    expect(screen.queryByText("Live Sandbox")).not.toBeInTheDocument();
    expect(screen.queryByText("connected")).not.toBeInTheDocument();
  });
});

describe("ApprovalRail", () => {
  afterEach(() => {
    vi.useRealTimers();
  });

  it("shows the confirmation dialog with accessible attributes and focus", () => {
    vi.useFakeTimers();
    render(
      <MissionProvider>
        <MissionControlPage />
      </MissionProvider>
    );

    act(() => {
      vi.advanceTimersByTime(3260);
    });

    const approveButton = screen.getByRole("button", {
      name: "Approve verified PR",
    });
    fireEvent.click(approveButton);

    const dialog = screen.getByRole("dialog");
    expect(dialog).toBeInTheDocument();
    expect(dialog).toHaveAttribute("aria-modal", "true");
    expect(dialog).toHaveAttribute("aria-labelledby");

    const cancelButton = screen.getByRole("button", { name: "Cancel" });
    expect(document.activeElement).toBe(cancelButton);
  });

  it("closes the dialog on Escape and restores focus to Approve", () => {
    vi.useFakeTimers();
    render(
      <MissionProvider>
        <MissionControlPage />
      </MissionProvider>
    );

    act(() => {
      vi.advanceTimersByTime(3260);
    });

    const approveButton = screen.getByRole("button", {
      name: "Approve verified PR",
    });
    fireEvent.click(approveButton);

    fireEvent.keyDown(document, { key: "Escape" });

    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(document.activeElement).toBe(approveButton);
  });
});

describe("workspace layout", () => {
  const workspaceOf = (container: HTMLElement) =>
    container.querySelector("main > div") as HTMLElement;

  it("reserves a rail column while the approval rail is rendered", () => {
    const { container } = render(
      <MissionProvider>
        <MissionControlPage />
      </MissionProvider>
    );

    expect(workspaceOf(container).style.gridTemplateColumns).toBe(
      "minmax(360px, 1fr) 270px"
    );
  });

  it("does not reserve a rail column when the rail is hidden", () => {
    const { container } = render(
      <MissionProvider>
        <MissionControlPage readOnly />
      </MissionProvider>
    );

    expect(workspaceOf(container).style.gridTemplateColumns).not.toMatch(/px/);
  });
});

describe("resizer drag", () => {
  const titles = [
    "Drag to resize rail",
    "Drag to resize dock",
    "Drag to resize inspector",
  ];

  it.each(titles)("suppresses text selection while dragging: %s", (title) => {
    render(
      <MissionProvider>
        <MissionControlPage />
      </MissionProvider>
    );

    fireEvent.pointerDown(screen.getByTitle(title), {
      clientX: 900,
      clientY: 400,
    });
    expect(document.body.style.userSelect).toBe("none");

    fireEvent.pointerUp(window);
    expect(document.body.style.userSelect).toBe("");
  });

  it.each(titles)("exposes each divider as a focusable separator: %s", (title) => {
    render(
      <MissionProvider>
        <MissionControlPage />
      </MissionProvider>
    );

    const divider = screen.getByTitle(title);
    expect(divider).toHaveAttribute("role", "separator");
    expect(divider).toHaveAttribute("tabindex", "0");
    expect(divider).toHaveAttribute("aria-valuenow");
    expect(divider.getAttribute("aria-label")).toBeTruthy();
  });

  it("resizes the rail from the keyboard", () => {
    const { container } = render(
      <MissionProvider>
        <MissionControlPage />
      </MissionProvider>
    );
    const workspace = container.querySelector("main > div") as HTMLElement;
    expect(workspace.style.gridTemplateColumns).toBe("minmax(360px, 1fr) 270px");

    fireEvent.keyDown(screen.getByTitle("Drag to resize rail"), {
      key: "ArrowLeft",
    });

    expect(workspace.style.gridTemplateColumns).toBe("minmax(360px, 1fr) 286px");
  });

  it.each(titles)("prevents the browser default drag on: %s", (title) => {
    render(
      <MissionProvider>
        <MissionControlPage />
      </MissionProvider>
    );

    const down = new PointerEvent("pointerdown", {
      bubbles: true,
      cancelable: true,
      clientX: 900,
      clientY: 400,
    });
    screen.getByTitle(title).dispatchEvent(down);

    expect(down.defaultPrevented).toBe(true);
    fireEvent.pointerUp(window);
  });
});
