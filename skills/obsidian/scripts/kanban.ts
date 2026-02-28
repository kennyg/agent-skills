#!/usr/bin/env bun
/**
 * Kanban CLI - Agent Mission Control
 *
 * Programmatic interface to obsidian-kanban boards.
 * Agents claim tasks, update status, and report results via file-based operations.
 *
 * Card format:
 *   - [ ] Task title [agent::claude-1] [status::in-progress] [priority::high] #agent-task #in-progress ^task-abc123
 *
 * Usage: bun kanban.ts <command> [args]
 */

import { $ } from "bun";

const VAULT = process.env.OBSIDIAN_VAULT;
const vaultArg = VAULT ? [`vault=${VAULT}`] : [];

// === Data Structures ===

interface KanbanItem {
  lineIndex: number;
  raw: string;
  checked: boolean;
  text: string;
  blockId?: string;
  fields: Record<string, string>;
  tags: string[];
  laneTitle: string;
}

interface KanbanLane {
  title: string;
  startLine: number;
  endLine: number; // exclusive
  items: KanbanItem[];
}

interface KanbanBoard {
  lanes: KanbanLane[];
  rawLines: string[];
  boardPath: string;
}

// === Parsing ===

function parseItem(line: string, lineIndex: number, laneTitle: string): KanbanItem | null {
  const itemMatch = line.match(/^- \[([ x])\] (.+)$/);
  if (!itemMatch) return null;

  const checked = itemMatch[1] === "x";
  const content = itemMatch[2];

  // Extract block ID at end of line
  const blockIdMatch = content.match(/\s+\^([a-zA-Z0-9-]+)$/);
  const blockId = blockIdMatch?.[1];

  // Extract inline fields [key::value]
  const fields: Record<string, string> = {};
  const fieldRegex = /\[([^\]:]+)::([^\]]+)\]/g;
  let fieldMatch;
  while ((fieldMatch = fieldRegex.exec(content)) !== null) {
    fields[fieldMatch[1].trim()] = fieldMatch[2].trim();
  }

  // Extract tags (avoid matching field-like constructs)
  const tags: string[] = [];
  const tagRegex = /#([\w-]+)/g;
  let tagMatch;
  // Strip fields first to avoid false tag matches inside [key::value]
  const contentNoFields = content.replace(/\[[^\]:]+::[^\]]+\]/g, "");
  while ((tagMatch = tagRegex.exec(contentNoFields)) !== null) {
    tags.push(tagMatch[1]);
  }

  // Clean text: remove fields, block ID, tags
  const text = content
    .replace(/\[[^\]:]+::[^\]]+\]/g, "")
    .replace(/\s+\^[a-zA-Z0-9-]+$/, "")
    .replace(/#[\w-]+/g, "")
    .replace(/\s{2,}/g, " ")
    .trim();

  return { lineIndex, raw: line, checked, text, blockId, fields, tags, laneTitle };
}

async function readBoard(boardPath: string): Promise<KanbanBoard> {
  const content = await $`obsidian read path=${boardPath} ${vaultArg}`.text();
  const rawLines = content.replace(/\n$/, "").split("\n");

  const lanes: KanbanLane[] = [];
  let currentLane: KanbanLane | null = null;

  for (let i = 0; i < rawLines.length; i++) {
    const line = rawLines[i];

    const laneMatch = line.match(/^## (.+)/);
    if (laneMatch) {
      // Close previous lane
      if (currentLane) {
        currentLane.endLine = i;
        lanes.push(currentLane);
      }
      currentLane = {
        title: laneMatch[1].trim(),
        startLine: i,
        endLine: rawLines.length,
        items: [],
      };
      continue;
    }

    if (currentLane) {
      const item = parseItem(line, i, currentLane.title);
      if (item) currentLane.items.push(item);
    }
  }

  if (currentLane) {
    currentLane.endLine = rawLines.length;
    lanes.push(currentLane);
  }

  return { lanes, rawLines, boardPath };
}

async function writeBoard(board: KanbanBoard): Promise<void> {
  const content = board.rawLines.join("\n") + "\n";
  await $`obsidian create path=${board.boardPath} content=${content} overwrite ${vaultArg}`.quiet();
}

function generateBlockId(prefix?: string): string {
  const id = Math.random().toString(36).slice(2, 11);
  return prefix ? `${prefix}-${id}` : id;
}

function findItemById(board: KanbanBoard, blockId: string): KanbanItem | null {
  for (const lane of board.lanes) {
    for (const item of lane.items) {
      if (item.blockId === blockId) return item;
    }
  }
  return null;
}

function findLane(board: KanbanBoard, laneTitle: string): KanbanLane | null {
  return board.lanes.find((l) => l.title.toLowerCase() === laneTitle.toLowerCase()) || null;
}

/**
 * Rebuild an item line from its components.
 * Preserves everything except specified field updates.
 */
function buildItemLine(
  item: KanbanItem,
  updates: { fields?: Record<string, string>; tags?: string[]; checked?: boolean },
): string {
  const checked = updates.checked !== undefined ? updates.checked : item.checked;
  const fields = { ...item.fields, ...updates.fields };
  const tags = updates.tags !== undefined ? updates.tags : item.tags;

  let line = `- [${checked ? "x" : " "}] ${item.text}`;

  // Append fields
  for (const [k, v] of Object.entries(fields)) {
    line += ` [${k}::${v}]`;
  }

  // Append tags
  if (tags.length > 0) {
    line += " " + tags.map((t) => `#${t}`).join(" ");
  }

  // Append block ID
  if (item.blockId) {
    line += ` ^${item.blockId}`;
  }

  return line;
}

/**
 * Move an item from its current lane to the target lane.
 * Mutates board.rawLines in place.
 */
function moveItem(
  board: KanbanBoard,
  item: KanbanItem,
  targetLaneName: string,
  newLine: string,
): void {
  const targetLane = findLane(board, targetLaneName);
  if (!targetLane) {
    throw new Error(`Lane "${targetLaneName}" not found`);
  }

  // Remove old line
  board.rawLines.splice(item.lineIndex, 1);

  // After removal, all lines after lineIndex shift by -1
  // Adjust target lane boundaries
  let insertIndex: number;
  if (item.lineIndex < targetLane.startLine) {
    // Item was before target lane — shift adjustments
    const adjustedStart = targetLane.startLine - 1;
    const adjustedEnd = targetLane.endLine - 1;

    // Find last item in the (now adjusted) target lane
    insertIndex = findInsertionPoint(board.rawLines, adjustedStart, adjustedEnd);
  } else {
    insertIndex = findInsertionPoint(board.rawLines, targetLane.startLine, targetLane.endLine);
  }

  board.rawLines.splice(insertIndex, 0, newLine);
}

/**
 * Find the insertion point for a new item in a lane.
 * Inserts after the last item line in the lane, before the next ## or end.
 */
function findInsertionPoint(lines: string[], laneStart: number, laneEnd: number): number {
  let lastItemLine = laneStart + 1; // default: right after lane header

  for (let i = laneStart + 1; i < Math.min(laneEnd, lines.length); i++) {
    if (lines[i].match(/^- \[/)) {
      lastItemLine = i + 1;
    } else if (lines[i].match(/^## /)) {
      break;
    }
  }

  return lastItemLine;
}

// === Status tag management ===

const STATUS_TAGS = ["in-progress", "blocked", "complete", "failed"];

function updateStatusTags(tags: string[], status: string): string[] {
  // Remove existing status tags
  const filtered = tags.filter((t) => !STATUS_TAGS.includes(t));
  // Map status values to tag names
  const tagName = status === "complete" ? "complete" : status;
  if (STATUS_TAGS.includes(tagName)) {
    filtered.push(tagName);
  }
  return filtered;
}

// === Commands ===

async function cmdBoardStatus(boardPath: string): Promise<void> {
  const board = await readBoard(boardPath);

  const result = {
    board: boardPath,
    lanes: board.lanes.map((lane) => ({
      title: lane.title,
      total: lane.items.length,
      unclaimed: lane.items.filter((i) => !i.fields.agent).length,
    })),
  };

  console.log(JSON.stringify(result, null, 2));
}

async function cmdList(
  boardPath: string,
  options: { lane?: string; agent?: string },
): Promise<void> {
  const board = await readBoard(boardPath);

  let items: KanbanItem[] = [];

  if (options.lane) {
    const lane = findLane(board, options.lane);
    if (!lane) {
      console.error(`Lane "${options.lane}" not found`);
      process.exit(1);
    }
    items = lane.items;
  } else {
    items = board.lanes.flatMap((l) => l.items);
  }

  if (options.agent) {
    items = items.filter((i) => i.fields.agent === options.agent);
  }

  const result = items.map((i) => ({
    id: i.blockId,
    text: i.text,
    lane: i.laneTitle,
    checked: i.checked,
    fields: i.fields,
    tags: i.tags,
  }));

  console.log(JSON.stringify(result, null, 2));
}

async function cmdClaim(boardPath: string, blockId: string, agentName: string): Promise<void> {
  const board = await readBoard(boardPath);

  const item = findItemById(board, blockId);
  if (!item) {
    console.error(`Item with id "${blockId}" not found`);
    process.exit(1);
  }

  if (item.fields.agent) {
    console.error(`Item "${blockId}" already claimed by "${item.fields.agent}"`);
    process.exit(1);
  }

  const newFields = {
    agent: agentName,
    status: "in-progress",
    claimed_at: new Date().toISOString().split("T")[0],
  };

  const newTags = updateStatusTags(item.tags, "in-progress");
  const newLine = buildItemLine(item, { fields: newFields, tags: newTags });

  moveItem(board, item, "In Progress", newLine);
  await writeBoard(board);

  console.log(
    JSON.stringify({ success: true, id: blockId, agent: agentName, lane: "In Progress" }),
  );
}

async function cmdUpdate(
  boardPath: string,
  blockId: string,
  status: string,
  note?: string,
): Promise<void> {
  const board = await readBoard(boardPath);

  const item = findItemById(board, blockId);
  if (!item) {
    console.error(`Item with id "${blockId}" not found`);
    process.exit(1);
  }

  const newFields: Record<string, string> = { status };
  if (note) newFields.note = note;

  const newTags = updateStatusTags(item.tags, status);
  const newLine = buildItemLine(item, { fields: newFields, tags: newTags });

  // Update in place (no lane move for generic update)
  board.rawLines[item.lineIndex] = newLine;
  await writeBoard(board);

  console.log(JSON.stringify({ success: true, id: blockId, status }));
}

async function cmdComplete(boardPath: string, blockId: string): Promise<void> {
  const board = await readBoard(boardPath);

  const item = findItemById(board, blockId);
  if (!item) {
    console.error(`Item with id "${blockId}" not found`);
    process.exit(1);
  }

  const newFields = {
    status: "complete",
    completed_at: new Date().toISOString().split("T")[0],
  };
  const newTags = updateStatusTags(item.tags, "complete");
  const newLine = buildItemLine(item, { fields: newFields, tags: newTags, checked: true });

  moveItem(board, item, "Done", newLine);
  await writeBoard(board);

  console.log(JSON.stringify({ success: true, id: blockId, lane: "Done" }));
}

async function cmdFail(boardPath: string, blockId: string, reason?: string): Promise<void> {
  const board = await readBoard(boardPath);

  const item = findItemById(board, blockId);
  if (!item) {
    console.error(`Item with id "${blockId}" not found`);
    process.exit(1);
  }

  const newFields: Record<string, string> = { status: "failed" };
  if (reason) newFields.reason = reason;

  const newTags = updateStatusTags(item.tags, "failed");
  const newLine = buildItemLine(item, { fields: newFields, tags: newTags });

  moveItem(board, item, "Failed", newLine);
  await writeBoard(board);

  console.log(JSON.stringify({ success: true, id: blockId, lane: "Failed" }));
}

async function cmdAddTask(
  boardPath: string,
  title: string,
  laneName: string,
  options: { priority?: string; fields?: Record<string, string> },
): Promise<void> {
  const board = await readBoard(boardPath);

  const lane = findLane(board, laneName);
  if (!lane) {
    console.error(`Lane "${laneName}" not found`);
    process.exit(1);
  }

  const blockId = generateBlockId();
  const fields: Record<string, string> = { ...options.fields };
  if (options.priority) fields.priority = options.priority;

  let line = `- [ ] ${title}`;

  for (const [k, v] of Object.entries(fields)) {
    line += ` [${k}::${v}]`;
  }

  line += ` #agent-task ^${blockId}`;

  const insertIndex = findInsertionPoint(board.rawLines, lane.startLine, lane.endLine);
  board.rawLines.splice(insertIndex, 0, line);
  await writeBoard(board);

  console.log(JSON.stringify({ success: true, id: blockId, lane: laneName, title }));
}

// === CLI ===

function parseArgs(argv: string[]): { positional: string[]; options: Record<string, string> } {
  const positional: string[] = [];
  const options: Record<string, string> = {};

  for (let i = 0; i < argv.length; i++) {
    if (argv[i].startsWith("--")) {
      const key = argv[i].slice(2);
      options[key] = argv[++i] || "";
    } else {
      positional.push(argv[i]);
    }
  }

  return { positional, options };
}

function parseFieldsArg(raw: string): Record<string, string> {
  const result: Record<string, string> = {};
  for (const pair of raw.split(",")) {
    const eqIdx = pair.indexOf("=");
    if (eqIdx > 0) {
      result[pair.slice(0, eqIdx).trim()] = pair.slice(eqIdx + 1).trim();
    }
  }
  return result;
}

const argv = process.argv.slice(2);
const command = argv[0];
const { options } = parseArgs(argv.slice(1));

function requireOption(name: string): string {
  const val = options[name];
  if (!val) {
    console.error(`Error: --${name} is required`);
    process.exit(1);
  }
  return val;
}

const commands: Record<string, () => Promise<void>> = {
  async "board-status"() {
    await cmdBoardStatus(requireOption("board"));
  },

  async list() {
    await cmdList(requireOption("board"), {
      lane: options.lane,
      agent: options.agent,
    });
  },

  async claim() {
    await cmdClaim(requireOption("board"), requireOption("id"), requireOption("agent"));
  },

  async update() {
    await cmdUpdate(
      requireOption("board"),
      requireOption("id"),
      requireOption("status"),
      options.note,
    );
  },

  async complete() {
    await cmdComplete(requireOption("board"), requireOption("id"));
  },

  async fail() {
    await cmdFail(requireOption("board"), requireOption("id"), options.reason);
  },

  async "add-task"() {
    const extraFields = options.fields ? parseFieldsArg(options.fields) : {};
    await cmdAddTask(requireOption("board"), requireOption("title"), requireOption("lane"), {
      priority: options.priority,
      fields: extraFields,
    });
  },
};

if (!command || !commands[command]) {
  console.log(`
Kanban CLI - Agent Mission Control

Usage: bun kanban.ts <command> [args]

Commands:
  board-status  --board <path>
      Show lane summary with item counts

  list          --board <path>  [--lane <name>]  [--agent <name>]
      List items as JSON (optionally filtered)

  claim         --board <path>  --id <blockId>  --agent <name>
      Claim a task from the Ready lane and move it to In Progress

  update        --board <path>  --id <blockId>  --status <value>  [--note <text>]
      Update status field (and status tag) on an item in place

  complete      --board <path>  --id <blockId>
      Mark item done and move to Done lane

  fail          --board <path>  --id <blockId>  [--reason <text>]
      Mark item failed and move to Failed lane

  add-task      --board <path>  --title <text>  --lane <name>
                [--priority high|medium|low]  [--fields key=val,...]
      Add a new task card

Examples:
  bun kanban.ts board-status --board "Agents/Mission-Control.md"
  bun kanban.ts list --board "Agents/Mission-Control.md" --lane Ready
  bun kanban.ts claim --board "Agents/Mission-Control.md" --id abc123def --agent claude-1
  bun kanban.ts update --board "Agents/Mission-Control.md" --id abc123def --status blocked --note "Waiting on API key"
  bun kanban.ts complete --board "Agents/Mission-Control.md" --id abc123def
  bun kanban.ts fail --board "Agents/Mission-Control.md" --id abc123def --reason "Build failed"
  bun kanban.ts add-task --board "Agents/Mission-Control.md" --title "Refactor auth module" --lane Backlog --priority high

Environment:
  OBSIDIAN_VAULT   Vault name to target (optional, defaults to active vault)
`);
  process.exit(command ? 1 : 0);
}

try {
  await commands[command]();
} catch (error) {
  console.error("Error:", error instanceof Error ? error.message : error);
  process.exit(1);
}
