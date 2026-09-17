"""The decide step: given the goal, step history, and current perceived
state, ask Claude for the single next action. Real Anthropic API call —
see agent/discover.py for the loop that drives this."""

import anthropic

MODEL = "claude-sonnet-5"

TOOL_NAME = "decide_next_action"

TOOL_SCHEMA = {
    "name": TOOL_NAME,
    "description": (
        "Decide the single next action to take toward the goal, or report "
        "that the goal is complete. Only one action per call."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "reasoning": {
                "type": "string",
                "description": "One or two sentences: what you observe and why this action moves toward the goal.",
            },
            "action": {
                "type": "string",
                "enum": ["click", "type", "navigate", "extract", "done"],
            },
            "role": {
                "type": "string",
                "description": "ARIA role of the target element (e.g. 'textbox', 'button'). Required for click and type.",
            },
            "name": {
                "type": "string",
                "description": "Accessible name of the target element, exactly as it appears in the accessibility tree. Required for click and type.",
            },
            "text": {
                "type": "string",
                "description": "Text to type into the target element. Required for type.",
            },
            "url": {
                "type": "string",
                "description": "Path to navigate to, e.g. '/'. Required for navigate.",
            },
            "label": {
                "type": "string",
                "description": "Exact text of a table row's label cell whose adjacent value cell should be read (e.g. 'Savings Balance'). Required for extract.",
            },
            "output_key": {
                "type": "string",
                "description": "Key name to store the extracted value under (e.g. 'savings_balance'). Required for extract.",
            },
            "goal_met": {
                "type": "boolean",
                "description": "Only for action=done: true if the goal was fully accomplished, false if giving up (e.g. a legitimate not-found result).",
            },
            "outputs": {
                "type": "object",
                "description": 'Only for action=done: the final collected key-value outputs, e.g. {"found": true, "member_name": "...", "savings_balance": "..."}.',
            },
        },
        "required": ["reasoning", "action"],
    },
}

SYSTEM_PROMPT = """You are a computer-use agent operating a web application \
through Playwright on behalf of a human operator. You act one step at a time.

Each turn you receive: the goal, a short history of prior steps, the \
current page's accessibility tree (your primary signal — reason about \
roles and accessible names, not visual position), and a screenshot of the \
current page (a backup signal, use it to sanity-check the tree).

Available actions:
- click: click an element identified by its accessibility role + accessible name.
- type: fill a text input identified by its accessibility role + accessible name.
- navigate: go to a specific path.
- extract: read a value out of a legacy label/value table row — give the \
exact text of the row's label cell (e.g. "Savings Balance") and a key to \
store the value under.
- done: report that the goal is complete (or that it cannot be completed, \
e.g. a legitimate "not found" result) and give the final outputs collected \
so far.

Use the exact accessible names as they appear in the accessibility tree — \
do not guess or paraphrase them. Take the most direct path to the goal. \
Call decide_next_action exactly once per turn."""


def decide_next_action(client: anthropic.Anthropic, goal: str, history: list, state: dict) -> dict:
    history_text = "\n".join(history) if history else "(no steps taken yet)"

    user_content = [
        {
            "type": "text",
            "text": (
                f"GOAL: {goal}\n\n"
                f"STEP HISTORY:\n{history_text}\n\n"
                f"CURRENT URL: {state['url']}\n"
                f"CURRENT PAGE TITLE: {state['title']}\n\n"
                f"CURRENT ACCESSIBILITY TREE (ARIA snapshot):\n{state['accessibility_tree']}"
            ),
        },
        {
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": "image/png",
                "data": state["screenshot_base64"],
            },
        },
    ]

    response = client.messages.create(
        model=MODEL,
        max_tokens=1024,
        thinking={"type": "disabled"},
        system=SYSTEM_PROMPT,
        tools=[TOOL_SCHEMA],
        tool_choice={"type": "tool", "name": TOOL_NAME},
        messages=[{"role": "user", "content": user_content}],
    )

    tool_use = next(b for b in response.content if b.type == "tool_use")
    return tool_use.input
