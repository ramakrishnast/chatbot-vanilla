import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { Composer } from "./Composer";

describe("Composer", () => {
  it("sends trimmed text on Enter and clears the box", async () => {
    const onSend = vi.fn();
    render(<Composer streaming={false} onSend={onSend} onStop={vi.fn()} />);
    const box = screen.getByLabelText("Message");

    await userEvent.type(box, "  hello world  {Enter}");

    expect(onSend).toHaveBeenCalledWith("hello world");
    expect(box).toHaveValue("");
  });

  it("inserts a newline on Shift+Enter instead of sending", async () => {
    const onSend = vi.fn();
    render(<Composer streaming={false} onSend={onSend} onStop={vi.fn()} />);
    const box = screen.getByLabelText("Message");

    await userEvent.type(box, "line one{Shift>}{Enter}{/Shift}line two");

    expect(onSend).not.toHaveBeenCalled();
    expect(box).toHaveValue("line one\nline two");
  });

  it("does not send blank messages", async () => {
    const onSend = vi.fn();
    render(<Composer streaming={false} onSend={onSend} onStop={vi.fn()} />);

    await userEvent.type(screen.getByLabelText("Message"), "   {Enter}");

    expect(onSend).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Send message" })).toBeDisabled();
  });

  it("shows a stop button while streaming", async () => {
    const onStop = vi.fn();
    const onSend = vi.fn();
    render(<Composer streaming onSend={onSend} onStop={onStop} />);

    await userEvent.click(screen.getByRole("button", { name: "Stop generating" }));
    await userEvent.type(screen.getByLabelText("Message"), "queued{Enter}");

    expect(onStop).toHaveBeenCalledOnce();
    expect(onSend).not.toHaveBeenCalled();
  });
});
