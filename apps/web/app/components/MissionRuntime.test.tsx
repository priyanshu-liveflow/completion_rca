import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import MissionRuntime from "./MissionRuntime";

describe("MissionRuntime", () => {
  it("renders in fixture mode without a live connection", () => {
    render(<MissionRuntime mode="fixture" />);
    expect(screen.getByText("Fixture replay")).toBeInTheDocument();
    expect(screen.queryByText("Live Sandbox")).not.toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Approve verified PR" })
    ).toBeDisabled();
  });

  it("renders live mode as idle before any stream events", () => {
    render(<MissionRuntime mode="live" />);
    expect(screen.getByText("TrueForge ready")).toBeInTheDocument();
  });
});
