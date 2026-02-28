#!/usr/bin/env bun
/**
 * Oncall Tracking CLI
 *
 * Lightweight incident logging to Obsidian vault.
 * Uses a single active shift file that gets archived when ended.
 *
 * Usage: bun oncall.ts <command> [args]
 */

import { $ } from "bun";

const VAULT = process.env.OBSIDIAN_VAULT;
const vaultArg = VAULT ? [`vault=${VAULT}`] : [];

const ONCALL_DIR = "Journal/Oncall";
const CURRENT_SHIFT = `${ONCALL_DIR}/current-shift.md`;
const ARCHIVE_DIR = `${ONCALL_DIR}/archive`;

function formatTime(): string {
  return new Date().toLocaleTimeString("en-US", {
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  });
}

function formatDate(): string {
  return new Date().toISOString().split("T")[0];
}

function parseFrontmatter(content: string): { frontmatter: Record<string, string>; body: string } {
  const match = content.match(/^---\n([\s\S]*?)\n---\n([\s\S]*)$/);
  if (!match) {
    return { frontmatter: {}, body: content };
  }

  const frontmatter: Record<string, string> = {};
  match[1].split("\n").forEach((line) => {
    const [key, ...valueParts] = line.split(":");
    if (key && valueParts.length) {
      frontmatter[key.trim()] = valueParts.join(":").trim();
    }
  });

  return { frontmatter, body: match[2] };
}

function createFrontmatter(meta: Record<string, string>): string {
  const lines = Object.entries(meta).map(([k, v]) => `${k}: ${v}`);
  return `---\n${lines.join("\n")}\n---\n`;
}

async function obsidianRead(path: string): Promise<string | null> {
  const content = await $`obsidian read path=${path} ${vaultArg}`.text();
  return content.startsWith("Error:") ? null : content;
}

async function obsidianWrite(path: string, content: string): Promise<void> {
  await $`obsidian create path=${path} content=${content} overwrite ${vaultArg}`.quiet();
}

async function obsidianDelete(path: string): Promise<void> {
  await $`obsidian delete path=${path} permanent ${vaultArg}`.quiet();
}

async function obsidianListFiles(folder: string): Promise<string[]> {
  const out = await $`obsidian files folder=${folder} ${vaultArg}`.text();
  if (out.startsWith("Error:")) return [];
  return out
    .trim()
    .split("\n")
    .filter((l) => l.endsWith(".md"));
}

// === Commands ===

async function start(): Promise<void> {
  if ((await obsidianRead(CURRENT_SHIFT)) !== null) {
    console.error('Error: Active shift already exists. Run "oncall end" first.');
    process.exit(1);
  }

  const date = formatDate();
  const time = formatTime();

  const content =
    createFrontmatter({
      startDate: date,
      startTime: time,
      status: "active",
    }) + `\n## Oncall Shift (${date})\n> Started: ${time}\n`;

  await obsidianWrite(CURRENT_SHIFT, content);
  console.log(`Oncall shift started at ${time}`);
}

async function log(message: string, tags: string[]): Promise<void> {
  if ((await obsidianRead(CURRENT_SHIFT)) === null) {
    console.error('Error: No active shift. Run "oncall start" first.');
    process.exit(1);
  }

  const time = formatTime();
  const tagStr = tags.length ? " " + tags.map((t) => `#${t}`).join(" ") : "";
  const entry = `- ${time} ${message}${tagStr}`;

  await $`obsidian append path=${CURRENT_SHIFT} content=${entry} ${vaultArg}`.quiet();
  console.log(`Logged: ${entry}`);
}

async function resolve(message: string, tags: string[]): Promise<void> {
  if ((await obsidianRead(CURRENT_SHIFT)) === null) {
    console.error('Error: No active shift. Run "oncall start" first.');
    process.exit(1);
  }

  const time = formatTime();
  const tagStr = "#resolved" + (tags.length ? " " + tags.map((t) => `#${t}`).join(" ") : "");
  const entry = `- ${time} ✓ ${message} ${tagStr}`;

  await $`obsidian append path=${CURRENT_SHIFT} content=${entry} ${vaultArg}`.quiet();
  console.log(`Logged: ${entry}`);
}

async function end(): Promise<void> {
  const content = await obsidianRead(CURRENT_SHIFT);
  if (content === null) {
    console.error("Error: No active shift to end.");
    process.exit(1);
  }

  const { frontmatter, body } = parseFrontmatter(content);
  const endDate = formatDate();
  const endTime = formatTime();

  const newContent =
    createFrontmatter({ ...frontmatter, endDate, endTime, status: "ended" }) +
    body +
    `> Ended: ${endTime}\n`;

  // Build archive path, avoid collisions
  const startDate = frontmatter.startDate || endDate;
  const base =
    startDate === endDate
      ? `${ARCHIVE_DIR}/${startDate}.md`
      : `${ARCHIVE_DIR}/${startDate}-to-${endDate}.md`;

  let archivePath = base;
  let counter = 1;
  while ((await obsidianRead(archivePath)) !== null) {
    archivePath = base.replace(".md", `-${++counter}.md`);
  }

  await obsidianWrite(archivePath, newContent);
  await obsidianDelete(CURRENT_SHIFT);

  console.log(`Oncall shift ended at ${endTime}`);
  console.log(`Archived to: ${archivePath}`);
}

async function summary(): Promise<void> {
  const content = await obsidianRead(CURRENT_SHIFT);
  if (content === null) {
    console.log("No active shift.");
    return;
  }

  const { body } = parseFrontmatter(content);
  console.log("=== Oncall Summary ===");
  console.log(body.trim());
  console.log("");

  const incidents = (body.match(/#incident/g) || []).length;
  const resolved = (body.match(/#resolved/g) || []).length;
  console.log(`Incidents: ${incidents} | Resolved: ${resolved}`);
}

async function search(query: string): Promise<void> {
  const lowerQuery = query.toLowerCase();
  let found = false;

  const current = await obsidianRead(CURRENT_SHIFT);
  if (current !== null) {
    const lines = current
      .split("\n")
      .filter((l) => l.toLowerCase().includes(lowerQuery) && l.startsWith("- "));
    if (lines.length) {
      found = true;
      console.log("=== Current Shift ===");
      lines.forEach((l) => console.log(l));
      console.log("");
    }
  }

  const archiveFiles = await obsidianListFiles(ARCHIVE_DIR);
  for (const file of archiveFiles.sort().reverse()) {
    const content = await obsidianRead(file);
    if (!content) continue;
    const lines = content
      .split("\n")
      .filter((l) => l.toLowerCase().includes(lowerQuery) && l.startsWith("- "));
    if (lines.length) {
      found = true;
      const filename = file.replace(`${ARCHIVE_DIR}/`, "");
      console.log(`=== ${filename} ===`);
      lines.forEach((l) => console.log(l));
      console.log("");
    }
  }

  if (!found) console.log("No matches found.");
}

async function list(): Promise<void> {
  console.log("=== Oncall Shifts ===");

  const current = await obsidianRead(CURRENT_SHIFT);
  if (current !== null) {
    const { frontmatter } = parseFrontmatter(current);
    console.log(
      `* current-shift.md (active since ${frontmatter.startDate} ${frontmatter.startTime})`,
    );
  }

  const files = await obsidianListFiles(ARCHIVE_DIR);
  files
    .sort()
    .reverse()
    .slice(0, 10)
    .forEach((f) => console.log(`  ${f.replace(`${ARCHIVE_DIR}/`, "")}`));

  if (files.length > 10) {
    console.log(`  ... and ${files.length - 10} more`);
  }
}

// === CLI Entry Point ===

const [command, ...args] = process.argv.slice(2);

const commands: Record<string, () => Promise<void>> = {
  async start() {
    await start();
  },

  async log() {
    if (!args[0]) {
      console.error("Usage: oncall log <message> [tags...]");
      process.exit(1);
    }
    await log(args[0], args.slice(1));
  },

  async resolve() {
    if (!args[0]) {
      console.error("Usage: oncall resolve <message> [tags...]");
      process.exit(1);
    }
    await resolve(args[0], args.slice(1));
  },

  async end() {
    await end();
  },

  async summary() {
    await summary();
  },

  async search() {
    if (!args[0]) {
      console.error("Usage: oncall search <query>");
      process.exit(1);
    }
    await search(args.join(" "));
  },

  async list() {
    await list();
  },
};

if (!command || !commands[command]) {
  console.log(`
Oncall Tracking CLI - Usage: bun oncall.ts <command> [args]

Commands:
  start                    Start a new oncall shift
  log <msg> [tags...]      Log an incident (e.g., oncall log "Alert fired" incident database)
  resolve <msg> [tags...]  Log a resolution (auto-adds #resolved)
  end                      End current shift and archive
  summary                  Show current shift summary
  search <query>           Search oncall logs
  list                     List recent shifts

Files:
  Journal/Oncall/current-shift.md    Active shift
  Journal/Oncall/archive/            Completed shifts

Examples:
  bun oncall.ts start
  bun oncall.ts log "PagerDuty alert for db-prod-01" incident database
  bun oncall.ts resolve "Increased connection pool" database
  bun oncall.ts end
`);
  process.exit(1);
}

try {
  await commands[command]();
} catch (error) {
  console.error("Error:", error instanceof Error ? error.message : error);
  process.exit(1);
}
