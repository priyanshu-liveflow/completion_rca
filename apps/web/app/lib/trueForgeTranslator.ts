import type { MissionEvent, TestLine, TestRunEvidence } from "./types";
import { SseMessage } from "./sseParser";
import {
  isTrueForgeSandboxCreated,
  isTrueForgeMissionSnapshot,
  TrueForgeMissionSnapshot,
  TrueForgeTestReport,
} from "./trueForgeTypes";

function safeJson(value: string): unknown | undefined {
  try {
    return JSON.parse(value);
  } catch {
    return undefined;
  }
}

export class TrueForgeTranslator {
  private sequence = 0;
  private sandboxId: string | null = null;
  private mission: TrueForgeMissionSnapshot | null = null;
  private redObserved = false;
  private emittedReportIds = new Set<string>();
  private selectionSeen = false;
  private impactSeen = false;
  private patchSeen = false;

  private nextId(): string {
    this.sequence += 1;
    return `tf-${String(this.sequence).padStart(6, "0")}`;
  }

  private makeLine(text: string, kind: TestLine["kind"] = "stdout", nodeId?: string): TestLine {
    const line: TestLine = { id: this.nextId(), text, kind };
    if (nodeId) line.nodeId = nodeId as TestLine["nodeId"];
    return line;
  }

  private getEventType(message: SseMessage): string | null {
    const parsed = safeJson(message.data);
    if (typeof parsed === "object" && parsed !== null && "type" in parsed) {
      return (parsed as { type: string }).type;
    }
    return message.event ?? null;
  }

  private getPayload(message: SseMessage): unknown {
    return safeJson(message.data);
  }

  translate(message: SseMessage): MissionEvent[] {
    const events: MissionEvent[] = [];
    const type = this.getEventType(message);
    if (!type) return events;

    const parsed = this.getPayload(message);

    switch (type) {
      case "turn.created": {
        const turnId =
          typeof parsed === "object" &&
          parsed !== null &&
          "turn_id" in (parsed as Record<string, unknown>)
            ? (parsed as { turn_id: string | null }).turn_id
            : null;
        events.push({ type: "runtime.turn.started", turnId });
        break;
      }

      case "turn.done":
        events.push({ type: "runtime.turn.completed" });
        break;

      case "model.message":
      case "model.message.delta":
      case "model.message.done":
        // Model prose is not part of the sandbox transcript.
        break;

      case "sandbox.created": {
        if (isTrueForgeSandboxCreated(parsed)) {
          this.sandboxId = parsed.sandbox_id;
          events.push({ type: "sandbox.connected", sandboxId: parsed.sandbox_id });
        }
        break;
      }

      case "tool.response":
        events.push(...this.handleToolResponse(parsed));
        break;

      default:
        // Unknown events are ignored, not synthesized.
        break;
    }

    return events;
  }

  private handleToolResponse(payload: unknown): MissionEvent[] {
    const events: MissionEvent[] = [];

    // The store can return a snapshot directly or wrapped in { success, response }.
    const wrapper = payload as { success?: boolean; response?: unknown } | null;
    const inner =
      typeof wrapper === "object" &&
      wrapper !== null &&
      "success" in wrapper &&
      wrapper.success === true
        ? wrapper.response
        : payload;

    if (isTrueForgeMissionSnapshot(inner)) {
      events.push(...this.diffMissionSnapshot(inner));
      return events;
    }

    // Generic sandbox command response: append output, never promote to evidence.
    const response =
      typeof wrapper === "object" &&
      wrapper !== null &&
      "success" in wrapper &&
      wrapper.success === true
        ? wrapper.response
        : payload;
    const command =
      typeof response === "object" &&
      response !== null &&
      ("exitCode" in (response as { exitCode?: number }) ||
        "result" in (response as { result?: string }))
        ? (response as { exitCode?: number; result?: string })
        : null;

    if (command) {
      const lines = (command.result ?? "")
        .split("\n")
        .filter((line) => line.length > 0);
      for (const line of lines) {
        events.push({
          type: "sandbox.line.appended",
          line: this.makeLine(line, "stdout"),
        });
      }
      events.push({
        type: "sandbox.line.appended",
        line: this.makeLine(
          `exit ${command.exitCode ?? "?"}`,
          "status",
        ),
      });
    }

    return events;
  }

  private diffMissionSnapshot(snapshot: TrueForgeMissionSnapshot): MissionEvent[] {
    const events: MissionEvent[] = [];
    const previous = this.mission;

    if (!previous) {
      events.push({
        type: "proof.node.updated",
        nodeId: "release",
        status: "amber",
      });
    }

    if (snapshot.selection && !this.selectionSeen) {
      this.selectionSeen = true;
      events.push({
        type: "proof.node.updated",
        nodeId: "tests",
        status: "static",
      });
    }

    const currentImpactCount = snapshot.impact_rows?.length ?? 0;
    if (currentImpactCount > (previous?.impact_rows?.length ?? 0) && !this.impactSeen) {
      this.impactSeen = true;
      events.push({
        type: "proof.node.updated",
        nodeId: "imports",
        status: "static",
      });
    }

    const selectionKey = snapshot.selection
      ? [...snapshot.selection.tests].sort().join(" ")
      : "";

    const previousReportIds = new Set(previous?.reports.map((r) => r.id) ?? []);
    for (const report of snapshot.reports) {
      if (previousReportIds.has(report.id) || this.emittedReportIds.has(report.id)) {
        continue;
      }
      this.emittedReportIds.add(report.id);
      events.push(...this.reportToEvents(report, snapshot, selectionKey));
    }

    const hasPatch =
      snapshot.verify !== null &&
      typeof snapshot.verify === "object" &&
      snapshot.verify.patch !== null;
    if (hasPatch && !this.patchSeen) {
      this.patchSeen = true;
      events.push({
        type: "patch.observed",
        patch: snapshot.verify!.patch,
      });
    }

    this.mission = snapshot;
    return events;
  }

  private reportToEvents(
    report: TrueForgeTestReport,
    snapshot: TrueForgeMissionSnapshot,
    selectionKey: string,
  ): MissionEvent[] {
    const events: MissionEvent[] = [];

    const isBroken = report.failed > 0 || report.errors > 0 || hasErrorCase(report);
    const evidence: TestRunEvidence = {
      runId: report.id,
      missionId: snapshot.id,
      sandboxId: this.sandboxId ?? "unknown",
      selectionKey,
      phase: "reproduce",
      exitCode: isBroken ? 1 : 0,
    };

    if (isBroken) {
      evidence.phase = "reproduce";
      this.redObserved = true;
      events.push({
        type: "tests.red_observed",
        failed: report.failed + report.errors,
        evidence,
      });
      for (const line of report.raw_tail.split("\n").filter(Boolean)) {
        events.push({
          type: "sandbox.line.appended",
          line: this.makeLine(line, "stderr", "errors"),
        });
      }
      return events;
    }

    if (report.passed > 0) {
      const isVerifyAfter =
        this.redObserved ||
        (snapshot.verify !== null &&
          snapshot.verify.after.id === report.id);
      evidence.phase = isVerifyAfter ? "verify" : "baseline";
      evidence.exitCode = 0;
      events.push({
        type: "tests.green_observed",
        passed: report.passed,
        evidence,
      });
      const nodeId = evidence.phase === "verify" ? "verify" : "tests";
      for (const line of report.raw_tail.split("\n").filter(Boolean)) {
        events.push({
          type: "sandbox.line.appended",
          line: this.makeLine(line, "stdout", nodeId),
        });
      }
    }

    return events;
  }
}

function hasErrorCase(report: TrueForgeTestReport): boolean {
  return report.cases?.some((c) => c.outcome === "error") ?? false;
}
