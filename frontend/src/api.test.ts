import { parseNdjson } from "./api";
import type { StreamEvent } from "./types";

function streamOf(...chunks: string[]): ReadableStream<Uint8Array> {
  const encoder = new TextEncoder();
  return new ReadableStream({
    start(controller) {
      for (const chunk of chunks) controller.enqueue(encoder.encode(chunk));
      controller.close();
    },
  });
}

async function collect(stream: ReadableStream<Uint8Array>): Promise<StreamEvent[]> {
  const events: StreamEvent[] = [];
  for await (const event of parseNdjson(stream)) events.push(event);
  return events;
}

describe("parseNdjson", () => {
  it("yields one event per line", async () => {
    const events = await collect(
      streamOf('{"type":"delta","content":"Hel"}\n{"type":"delta","content":"lo"}\n'),
    );
    expect(events).toEqual([
      { type: "delta", content: "Hel" },
      { type: "delta", content: "lo" },
    ]);
  });

  it("joins lines split across network chunks and handles a missing final newline", async () => {
    const events = await collect(
      streamOf('{"type":"del', 'ta","content":"a"}\n\n{"type":"title",', '"title":"T"}'),
    );
    expect(events).toEqual([
      { type: "delta", content: "a" },
      { type: "title", title: "T" },
    ]);
  });

  it("keeps multi-byte characters split across chunks intact", async () => {
    const bytes = new TextEncoder().encode('{"type":"delta","content":"héllo 👋"}\n');
    const stream = new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(bytes.slice(0, 30));
        controller.enqueue(bytes.slice(30));
        controller.close();
      },
    });
    expect(await collect(stream)).toEqual([{ type: "delta", content: "héllo 👋" }]);
  });
});
