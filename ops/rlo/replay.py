"""Synthetic replay: W1-typical tool calls through rlo.hooks (enforce) with candidate models. Numbers/labels only."""
import copy, io, json, sys
from rlo.hooks import main as hook_main
H = "/tmp/claude-0/-home-user/848b9e67-af02-5fb3-8bd9-7016023c738f/scratchpad/amphub"
W = H + "/.ga/worktrees/W1/amp"
CALLS = [
 ("Bash", {"command": "ls"}),
 ("Read", {"file_path": W + "/PREP.md"}),
 ("Read", {"file_path": W + "/PREP.md", "offset": 1, "limit": 50}),
 ("Glob", {"pattern": "**/*.py", "path": W}),
 ("Grep", {"pattern": "def ", "path": W}),
 ("Grep", {"pattern": "def ", "path": W, "output_mode": "content", "-n": True}),
 ("Write", {"file_path": W + "/amp/forms.py", "content": "x = 1\n"}),
 ("Edit", {"file_path": W + "/amp/forms.py", "old_string": "x = 1", "new_string": "x = 2"}),
 ("Bash", {"command": H + "/bin/amp-test " + W, "description": "run tests"}),
 ("Bash", {"command": "git add -A"}),
 ("Bash", {"command": "git commit -m 'CMD-WA1: forms'"}),
 ("Write", {"file_path": W + "/../report.md", "content": "r"}),
 ("Bash", {"command": "python -m ga post --channel W1 --from W1 report.md"}),
]
def run(model_path, grants):
    lines, out = [], []
    base = 1790899200000  # 2026-10-02T00:00:00Z
    for i, (tool, inp) in enumerate(CALLS):
        tu = f"tu{i+1}"
        ts = lambda k: f"2026-10-02T00:{i:02d}:{k:02d}.000Z"
        if i == 0:
            lines.append({"type": "user", "sessionId": "s1", "uuid": "u0", "timestamp": ts(0), "message": {"role": "user", "content": "go"}})
        lines.append({"type": "assistant", "sessionId": "s1", "uuid": f"a{i}", "timestamp": ts(1), "message": {"id": f"m{i}", "model": "claude-haiku", "role": "assistant", "stop_reason": "tool_use", "usage": {"input_tokens": 100, "output_tokens": 10}, "content": [{"type": "tool_use", "id": tu, "name": tool, "input": inp}]}})
        tp = f"t_{i}.jsonl"
        with open(tp, "w") as f:
            f.write("\n".join(json.dumps(l) for l in lines) + "\n")
        hook = {"session_id": "s1", "transcript_path": tp, "cwd": W, "permission_mode": "acceptEdits", "hook_event_name": "PreToolUse", "tool_name": tool, "tool_input": inp, "tool_use_id": tu}
        argv = ["--model", model_path, "--mode", "enforce", "--now-ms", str(base + i * 60000 + 2000)] + sum((["--grant", g] for g in grants), [])
        so = io.StringIO(); hook_main(argv, io.StringIO(json.dumps(hook)), so)
        r = json.loads(so.getvalue() or "{}")
        dec = r.get("hookSpecificOutput", {}).get("permissionDecision", "allow({})")
        reason = r.get("hookSpecificOutput", {}).get("permissionDecisionReason", "")
        out.append((tool, dec, reason[:90]))
        # tool result so the next call sees a finished prior call
        lines.append({"type": "user", "sessionId": "s1", "uuid": f"r{i}", "timestamp": ts(3), "toolUseResult": {}, "message": {"role": "user", "content": [{"type": "tool_result", "tool_use_id": tu, "content": [{"type": "text", "text": "ok"}], "is_error": False}]}})
    return out
if __name__ == "__main__":
    res = run(sys.argv[1], sys.argv[2:])
    for t, d, r in res: print(f"{t:6} {d:10} {r}")
    print("allow", sum(d != "deny" for _, d, _ in res), "deny", sum(d == "deny" for _, d, _ in res))
