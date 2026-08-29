import { act, render, screen } from "@testing-library/react";
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
