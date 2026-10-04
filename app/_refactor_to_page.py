import re
import shutil
from pathlib import Path

PATH = Path(__file__).parent / "main.py"
BACKUP = Path(__file__).parent / "main.py.bak"

shutil.copyfile(PATH, BACKUP)

lines = PATH.read_text(encoding="utf-8").splitlines(keepends=True)


def find_idx(predicate, start=0):
    for i in range(start, len(lines)):
        if predicate(lines[i]):
            return i
    raise ValueError("pattern not found")


# --- 1. Extract selected_model / selected_effort init lines ---
i_sel_model = find_idx(lambda l: l.startswith("selected_model ="))
assert lines[i_sel_model + 1].startswith("selected_effort ="), lines[i_sel_model + 1]
selected_init_lines = lines[i_sel_model:i_sel_model + 2]
del lines[i_sel_model:i_sel_model + 2]

# --- 2. Extract the state block (chats ... generation_mode) ---
i_state = find_idx(lambda l: l.startswith("chats = []"))
# the block is exactly 8 lines: chats, current_messages, chat_counter,
# active_chat_id, pending_attachments, generation_task, generation_cancelled, generation_mode
state_block_lines = lines[i_state:i_state + 8]
expected_starts = [
    "chats = []", "current_messages = []", "chat_counter = 1", "active_chat_id = None",
    "pending_attachments = []", "generation_task = None", "generation_cancelled = False",
    "generation_mode = \"chat\"",
]
for line, expected in zip(state_block_lines, expected_starts):
    assert line.startswith(expected), (line, expected)
del lines[i_state:i_state + 8]

# --- 3. Remove the redundant duplicate "chats = []" / "chat_counter = 1" ---
i_dup = find_idx(lambda l: l.startswith("chats = []"))
assert lines[i_dup + 1].startswith("chat_counter = 1"), lines[i_dup + 1]
del lines[i_dup:i_dup + 2]

# --- 4. Find the start of the UI/handler block (first helper def) ---
i_start = find_idx(lambda l: l.startswith("def load_persisted_chats"))

# --- 5. Find the end boundary: the "# Run" comment block right before ui.run( ---
i_run_comment = find_idx(lambda l: l.strip() == "# Run")
# back up to the opening "# ====" line of that comment block
i_end = i_run_comment - 1
while not lines[i_end].strip().startswith("# ==="):
    i_end -= 1
# i_end now points at the opening separator line of the "# Run" banner;
# everything strictly before i_end belongs inside index()

# --- 6. Build the new index() header + relocated state inits ---
header = [
    "@ui.page('/')\n",
    "def index() -> None:\n",
]
indented_inits = ["    " + l if l.strip() else l for l in selected_init_lines + state_block_lines]

# --- 7. Indent the whole UI/handler block by 4 spaces ---
block = lines[i_start:i_end]
indented_block = ["    " + l if l.strip() else l for l in block]

# --- 8. Convert "global X" -> "nonlocal X" for the relocated state vars ---
state_vars = {
    "chats", "current_messages", "chat_counter", "active_chat_id", "pending_attachments",
    "generation_task", "generation_cancelled", "generation_mode", "selected_model",
    "selected_effort", "sidebar_collapsed",
}
global_re = re.compile(r"^(\s*)global (.+)$")


def fix_global(line: str) -> str:
    m = global_re.match(line.rstrip("\n"))
    if not m:
        return line
    indent, names = m.groups()
    names_list = [n.strip() for n in names.split(",")]
    assert all(n in state_vars for n in names_list), names_list
    newline = "\n" if line.endswith("\n") else ""
    return f"{indent}nonlocal {', '.join(names_list)}{newline}"


indented_block = [fix_global(l) for l in indented_block]

# --- 9. Reassemble the file ---
new_lines = lines[:i_start] + header + indented_inits + ["\n"] + indented_block + lines[i_end:]
PATH.write_text("".join(new_lines), encoding="utf-8")
print("OK: refactor applied. Backup at", BACKUP)
