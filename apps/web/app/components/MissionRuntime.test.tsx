import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import MissionRuntime from "./MissionRuntime";

describe("MissionRuntime", () => {
  it("renders in fixture mode without a live connection", () => {
    render(<MissionRuntime mode="fixture" />);
    expect(
      screen.getByText("Runtime: fixture replay · fixture")
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Approve verified PR" })
    ).toBeDisabled();
  });

  it("renders in live mode label", () => {
    render(<MissionRuntime mode="live" />);
    expect(screen.getByText(/Runtime: live ·/)).toBeInTheDocument();
  });
});
