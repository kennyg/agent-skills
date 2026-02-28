#!/usr/bin/env bun
/**
 * Todo CLI - Obsidian Tasks integration
 *
 * Uses Obsidian Tasks plugin format:
 * - [ ] Task #tag 📅 2025-12-30 ➕ 2025-12-29
 *
 * Usage: bun todo.ts <command> [args]
 */

import { $ } from "bun";

const VAULT = process.env.OBSIDIAN_VAULT;
const vaultArg = VAULT ? [`vault=${VAULT}`] : [];

const TODO_FILE = process.env.OBSIDIAN_TODO_FILE || "Inbox/Tasks.md";

// Task plugin emoji format
const EMOJI = {
  due: "📅",
  created: "➕",
  done: "✅",
  scheduled: "⏳",
  start: "🛫",
  high: "⏫",
  medium: "🔼",
  low: "🔽",
};

interface Task {
  line: number;
  raw: string;
  done: boolean;
  text: string;
  tags: string[];
  due?: string;
  created?: string;
  priority?: "high" | "medium" | "low";
}

function formatDate(date?: Date): string {
  return (date || new Date()).toISOString().split("T")[0];
}

function parseTask(line: string, lineNum: number): Task | null {
  const match = line.match(/^- \[([ x])\] (.+)$/);
  if (!match) return null;

  const done = match[1] === "x";
  const content = match[2];

  // Extract tags
  const tags = (content.match(/#[\w-]+/g) || []).map((t) => t.slice(1));

  // Extract dates
  const dueMatch = content.match(/📅 (\d{4}-\d{2}-\d{2})/);
  const createdMatch = content.match(/➕ (\d{4}-\d{2}-\d{2})/);

  // Extract priority
  let priority: "high" | "medium" | "low" | undefined;
  if (content.includes("⏫")) priority = "high";
  else if (content.includes("🔼")) priority = "medium";
  else if (content.includes("🔽")) priority = "low";

  // Clean text (remove metadata)
  const text = content
    .replace(/#[\w-]+/g, "")
    .replace(/[📅➕✅⏳🛫⏫🔼🔽] \d{4}-\d{2}-\d{2}/g, "")
    .replace(/[⏫🔼🔽]/g, "")
    .trim();

  return {
    line: lineNum,
    raw: line,
    done,
    text,
    tags,
    due: dueMatch?.[1],
    created: createdMatch?.[1],
    priority,
  };
}

async function readTasks(): Promise<{ tasks: Task[]; lines: string[] }> {
  const content = await $`obsidian read path=${TODO_FILE} ${vaultArg}`.text();
  if (content.startsWith("Error:")) return { tasks: [], lines: [] };

  // Remove trailing newline before splitting to avoid empty last element
  const lines = content.replace(/\n$/, "").split("\n");
  const tasks: Task[] = [];

  lines.forEach((line, i) => {
    const task = parseTask(line, i);
    if (task) tasks.push(task);
  });

  return { tasks, lines };
}

async function writeTasks(lines: string[]): Promise<void> {
  // Filter empty lines, add trailing newline
  const cleaned = lines.filter((l) => l.trim());
  await $`obsidian create path=${TODO_FILE} content=${cleaned.join("\n") + "\n"} overwrite ${vaultArg}`.quiet();
}

async function add(
  text: string,
  tags: string[],
  options: { due?: string; priority?: string },
): Promise<void> {
  const { lines } = await readTasks();

  let task = `- [ ] ${text}`;

  // Add tags
  if (tags.length) {
    task += " " + tags.map((t) => `#${t}`).join(" ");
  }

  // Add priority
  if (options.priority) {
    const p = options.priority.toLowerCase();
    if (p === "high" || p === "h") task += ` ${EMOJI.high}`;
    else if (p === "medium" || p === "med" || p === "m") task += ` ${EMOJI.medium}`;
    else if (p === "low" || p === "l") task += ` ${EMOJI.low}`;
  }

  // Add due date
  if (options.due) {
    const due =
      options.due === "today"
        ? formatDate()
        : options.due === "tomorrow"
          ? formatDate(new Date(Date.now() + 86400000))
          : options.due;
    task += ` ${EMOJI.due} ${due}`;
  }

  // Add created date
  task += ` ${EMOJI.created} ${formatDate()}`;

  lines.push(task);
  await writeTasks(lines);
  console.log(`Added: ${task}`);
}

function sortTasks(tasks: Task[]): Task[] {
  return [...tasks].sort((a, b) => {
    const pOrder = { high: 0, medium: 1, low: 2, undefined: 3 };
    const pDiff =
      (pOrder[a.priority as keyof typeof pOrder] ?? 3) -
      (pOrder[b.priority as keyof typeof pOrder] ?? 3);
    if (pDiff !== 0) return pDiff;

    if (a.due && b.due) return a.due.localeCompare(b.due);
    if (a.due) return -1;
    if (b.due) return 1;
    return 0;
  });
}

async function done(query: string): Promise<void> {
  const { tasks, lines } = await readTasks();

  // Find by line number or text search
  const num = parseInt(query);
  let task: Task | undefined;

  if (!isNaN(num)) {
    // Find nth incomplete task (sorted same as list display)
    const incomplete = sortTasks(tasks.filter((t) => !t.done));
    task = incomplete[num - 1];
  } else {
    // Search by text
    const lower = query.toLowerCase();
    task = tasks.find((t) => !t.done && t.text.toLowerCase().includes(lower));
  }

  if (!task) {
    console.error("Task not found");
    process.exit(1);
  }

  // Mark as done
  const updated = task.raw.replace("- [ ]", "- [x]") + ` ${EMOJI.done} ${formatDate()}`;

  lines[task.line] = updated;
  await writeTasks(lines);
  console.log(`Done: ${task.text}`);
}

async function del(query: string): Promise<void> {
  const { tasks, lines } = await readTasks();

  // Find by line number or text search
  const num = parseInt(query);
  let task: Task | undefined;

  if (!isNaN(num)) {
    // Find nth incomplete task (sorted same as list display)
    const incomplete = sortTasks(tasks.filter((t) => !t.done));
    task = incomplete[num - 1];
  } else {
    // Search by text
    const lower = query.toLowerCase();
    task = tasks.find((t) => !t.done && t.text.toLowerCase().includes(lower));
  }

  if (!task) {
    console.error("Task not found");
    process.exit(1);
  }

  // Remove the line
  lines.splice(task.line, 1);
  await writeTasks(lines);
  console.log(`Deleted: ${task.text}`);
}

async function list(filter?: string): Promise<void> {
  const { tasks } = await readTasks();

  let filtered = tasks.filter((t) => !t.done);

  if (filter) {
    const lower = filter.toLowerCase();
    filtered = filtered.filter(
      (t) =>
        t.text.toLowerCase().includes(lower) ||
        t.tags.some((tag) => tag.toLowerCase().includes(lower)),
    );
  }

  if (filtered.length === 0) {
    console.log("No tasks found.");
    return;
  }

  const sorted = sortTasks(filtered);

  sorted.forEach((t, i) => {
    const priority = t.priority ? ` ${EMOJI[t.priority]}` : "";
    const due = t.due ? ` ${EMOJI.due} ${t.due}` : "";
    const tags = t.tags.length ? ` ${t.tags.map((x) => `#${x}`).join(" ")}` : "";
    console.log(`${i + 1}. ${t.text}${priority}${due}${tags}`);
  });
}

async function listAll(): Promise<void> {
  const { tasks } = await readTasks();

  const incomplete = tasks.filter((t) => !t.done);
  const complete = tasks.filter((t) => t.done).slice(-5);

  if (incomplete.length) {
    console.log("=== Pending ===");
    incomplete.forEach((t, i) => {
      const priority = t.priority ? ` ${EMOJI[t.priority]}` : "";
      const due = t.due ? ` ${EMOJI.due} ${t.due}` : "";
      console.log(`${i + 1}. ${t.text}${priority}${due}`);
    });
  }

  if (complete.length) {
    console.log("\n=== Recently Done ===");
    complete.forEach((t) => {
      console.log(`✓ ${t.text}`);
    });
  }

  if (!incomplete.length && !complete.length) {
    console.log("No tasks.");
  }
}

// === CLI ===

const args = process.argv.slice(2);
const command = args[0];

function parseArgs(args: string[]): { positional: string[]; options: Record<string, string> } {
  const positional: string[] = [];
  const options: Record<string, string> = {};

  for (let i = 0; i < args.length; i++) {
    if (args[i].startsWith("--")) {
      const key = args[i].slice(2);
      options[key] = args[++i] || "";
    } else {
      positional.push(args[i]);
    }
  }

  return { positional, options };
}

const commands: Record<string, () => Promise<void>> = {
  async add() {
    const { positional, options } = parseArgs(args.slice(1));
    if (!positional[0]) {
      console.error('Usage: todo add "task" [tags...] [--due DATE] [--priority high|med|low]');
      process.exit(1);
    }
    const [text, ...tags] = positional;
    await add(text, tags, { due: options.due, priority: options.priority });
  },

  async done() {
    if (!args[1]) {
      console.error("Usage: todo done <number or search>");
      process.exit(1);
    }
    await done(args.slice(1).join(" "));
  },

  async delete() {
    if (!args[1]) {
      console.error("Usage: todo delete <number or search>");
      process.exit(1);
    }
    await del(args.slice(1).join(" "));
  },

  async list() {
    await list(args[1]);
  },

  async all() {
    await listAll();
  },
};

if (!command || !commands[command]) {
  console.log(`
Todo CLI - Obsidian Tasks integration

Usage: bun todo.ts <command> [args]

Commands:
  add <text> [tags...] [--due DATE] [--priority high|med|low]
      Add a new task. DATE can be YYYY-MM-DD, "today", or "tomorrow"

  done <number or search>
      Mark a task as complete (by list number or text search)

  delete <number or search>
      Remove a task entirely (by list number or text search)

  list [filter]
      Show pending tasks (optionally filtered by text/tag)

  all
      Show pending + recently completed tasks

Examples:
  bun todo.ts add "Review PR" work --due tomorrow --priority high
  bun todo.ts add "Buy groceries" personal errands
  bun todo.ts done 1
  bun todo.ts done "PR"
  bun todo.ts list work
  bun todo.ts all

File: ${TODO_FILE}${VAULT ? ` (vault: ${VAULT})` : ""}
`);
  process.exit(command ? 1 : 0);
}

try {
  await commands[command]();
} catch (error) {
  console.error("Error:", error instanceof Error ? error.message : error);
  process.exit(1);
}
