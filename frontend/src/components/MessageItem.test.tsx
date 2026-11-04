import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import type { Message } from "../types";
import { MessageItem } from "./MessageItem";

function message(overrides: Partial<Message>): Message {
  return {
    id: "6f1c1d1e-0000-4000-8000-000000000001",
    position: 0,
    role: "assistant",
    content: "",
    thinking: null,
    model: "qwen3:0.6b",
    status: "complete",
    created_at: "2026-11-04T12:00:00Z",
    ...overrides,
  };
}

const noop = () => undefined;

describe("MessageItem", () => {
  it("renders assistant Markdown with a highlighted, copyable code block", () => {
    const { container } = render(
      <MessageItem
        message={message({ content: "Use **bold**:\n\n```python\nprint('hi')\n```" })}
        isLast
        canAct
        onRegenerate={noop}
        onEdit={noop}
      />,
    );

    expect(screen.getByText("bold").tagName).toBe("STRONG");
    expect(screen.getByText("python")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Copy code" })).toBeInTheDocument();
    expect(container.querySelector("code.hljs")).not.toBeNull();
  });

  it("does not render raw HTML from the model", () => {
    const { container } = render(
      <MessageItem
        message={message({ content: "<img src=x onerror=alert(1)> hi" })}
        isLast
        canAct
        onRegenerate={noop}
        onEdit={noop}
      />,
    );
    expect(container.querySelector("img")).toBeNull();
  });

  it("offers Regenerate only on the last reply and only when idle", async () => {
    const onRegenerate = vi.fn();
    const { rerender } = render(
      <MessageItem
        message={message({ content: "hi" })}
        isLast={false}
        canAct
        onRegenerate={onRegenerate}
        onEdit={noop}
      />,
    );
    expect(screen.queryByRole("button", { name: "Regenerate" })).toBeNull();

    rerender(
      <MessageItem
        message={message({ content: "hi" })}
        isLast
        canAct
        onRegenerate={onRegenerate}
        onEdit={noop}
      />,
    );
    await userEvent.click(screen.getByRole("button", { name: "Regenerate" }));
    expect(onRegenerate).toHaveBeenCalledOnce();
  });

  it("shows the thought process and a stopped note", () => {
    render(
      <MessageItem
        message={message({ content: "partial", thinking: "considering…", status: "stopped" })}
        isLast
        canAct
        onRegenerate={noop}
        onEdit={noop}
      />,
    );
    expect(screen.getByText("Thought process")).toBeInTheDocument();
    expect(screen.getByText("Stopped.")).toBeInTheDocument();
  });

  it("lets the user edit and resubmit their message", async () => {
    const onEdit = vi.fn();
    const user = message({ role: "user", content: "What is 2+2?" });
    render(
      <MessageItem message={user} isLast={false} canAct onRegenerate={noop} onEdit={onEdit} />,
    );

    await userEvent.click(screen.getByRole("button", { name: "Edit" }));
    const box = screen.getByLabelText("Edit message");
    await userEvent.clear(box);
    await userEvent.type(box, "What is 3+3?");
    await userEvent.click(screen.getByRole("button", { name: "Save & submit" }));

    expect(onEdit).toHaveBeenCalledWith(user.id, "What is 3+3?");
  });
});
