import { MissionAdapter, MissionDispatch } from "./missionAdapter";
import { MissionEvent } from "./types";
import { SseParser } from "./sseParser";
import { TrueForgeTranslator } from "./trueForgeTranslator";
import { TrueForgeTransport } from "./trueForgeTransport";

/**
 * Live MissionAdapter backed by a TrueForge session stream.
 *
 * The adapter does not claim a live sandbox until a `sandbox.created` event is
 * observed. Translation is driven by the captured SSE fixture and the
 * documented mission-snapshot contract rather than guesses about tool names.
 */
export function createTrueForgeMissionAdapter(
  transport = new TrueForgeTransport()
): MissionAdapter {
  return new TrueForgeMissionAdapter(transport);
}

export class TrueForgeMissionAdapter implements MissionAdapter {
  readonly mode = "live" as const;
  private transport: TrueForgeTransport;
  private _dispatch: MissionDispatch | null = null;
  private parser = new SseParser();
  private translator = new TrueForgeTranslator();
  private controller: AbortController | null = null;
  private generation = 0;

  constructor(transport: TrueForgeTransport) {
    this.transport = transport;
  }

  subscribe(dispatch: MissionDispatch): () => void {
    this._dispatch = dispatch;
    this.generation += 1;
    const startedGeneration = this.generation;
    this.controller = new AbortController();
    this.parser = new SseParser();
    this.translator = new TrueForgeTranslator();

    const signal = this.controller.signal;

    const start = async () => {
      if (this.generation !== startedGeneration || signal.aborted) return;
      this.emit({ type: "runtime.connecting" });

      try {
        await this.transport.createSession();
        if (this.generation !== startedGeneration || signal.aborted) return;

        const sessionId = this.transport.getSessionId() ?? "";
        this.emit({ type: "runtime.connected", sessionId });

        this.emit({ type: "runtime.turn.started", turnId: null });

        await this.transport.startTurn(
          undefined,
          (chunk) => this.handleChunk(startedGeneration, chunk),
          signal,
        );
      } catch (error) {
        if (this.generation !== startedGeneration) return;
        const message =
          error instanceof Error && error.name !== "AbortError"
            ? error.message
            : "Unknown TrueForge error";
        if (error instanceof Error && error.name === "AbortError") return;
        this.emit({ type: "runtime.failed", message });
      }
    };

    queueMicrotask(start);

    return () => this.unsubscribe(startedGeneration);
  }

  private emit(event: MissionEvent) {
    if (this._dispatch) this._dispatch(event);
  }

  private handleChunk(expectedGeneration: number, chunk: string) {
    if (this.generation !== expectedGeneration) return;
    this.parser.append(chunk);

    let message = this.parser.nextMessage();
    while (message) {
      const events = this.translator.translate(message);
      for (const event of events) {
        this.emit(event);
      }
      message = this.parser.nextMessage();
    }
  }

  private unsubscribe(expectedGeneration: number) {
    if (this.generation !== expectedGeneration) return;
    this.generation += 1;
    if (this.controller) {
      this.controller.abort();
      this.controller = null;
    }
    this._dispatch = null;
  }
}
