import { spawn } from "node:child_process";
import path from "node:path";

// Node, not Edge: this streams the output of a real child process.
export const runtime = "nodejs";
export const dynamic = "force-dynamic";

/**
 * Run the repair demo and stream its progress to the browser.
 *
 * There is no request body and nothing from the client reaches the command
 * line. The script and its arguments are fixed here, so this endpoint can
 * start exactly one known process and cannot be turned into a shell. It is a
 * local dashboard control, not a general runner.
 *
 * Streamed as newline-delimited text rather than SSE: the client only needs
 * "here is the next line", and SSE would add an event framing that both sides
 * would then have to strip.
 */
export async function POST(request: Request) {
  const url = new URL(request.url);
  const canned = url.searchParams.get("canned") === "1";

  const repoRoot = path.join(process.cwd(), "..", "..");
  const args = ["scripts/demo_repair.py"];
  if (canned) args.push("--canned");

  const child = spawn(".venv/bin/python", args, {
    cwd: repoRoot,
    env: { ...process.env, PYTHONUNBUFFERED: "1" },
  });

  const encoder = new TextEncoder();
  const stream = new ReadableStream<Uint8Array>({
    start(controller) {
      let closed = false;
      const send = (text: string) => {
        if (!closed) controller.enqueue(encoder.encode(text));
      };

      // The script writes its narration to stdout and Python tracebacks to
      // stderr. Both belong in the pane: a run that died is exactly what a
      // viewer needs to see, and hiding stderr would show a run that simply
      // stopped for no visible reason.
      child.stdout.on("data", (chunk) => send(chunk.toString()));
      child.stderr.on("data", (chunk) => send(chunk.toString()));

      child.on("error", (err) => {
        send(`\ncould not start the repair: ${err.message}\n`);
        if (!closed) {
          closed = true;
          controller.close();
        }
      });

      child.on("close", (code) => {
        send(`\n__EXIT__ ${code ?? -1}\n`);
        if (!closed) {
          closed = true;
          controller.close();
        }
      });

      // A viewer navigating away must not leave a python process behind.
      request.signal.addEventListener("abort", () => {
        child.kill("SIGTERM");
      });
    },
    cancel() {
      child.kill("SIGTERM");
    },
  });

  return new Response(stream, {
    headers: {
      "Content-Type": "text/plain; charset=utf-8",
      "Cache-Control": "no-store, no-transform",
      "X-Accel-Buffering": "no",
    },
  });
}
