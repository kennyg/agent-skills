#!/usr/bin/env bun
/**
 * Thought CLI - Quick notes to daily journal
 *
 * Usage: bun thought.ts <message> [tags...]
 */

import { $ } from "bun";

const VAULT = process.env.OBSIDIAN_VAULT;
const vaultArg = VAULT ? [`vault=${VAULT}`] : [];

function formatTime(): string {
  return new Date().toLocaleTimeString("en-US", {
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  });
}

// === CLI ===

const args = process.argv.slice(2);

if (args.length === 0 || args[0] === "--help" || args[0] === "-h") {
  console.log(`
Thought CLI - Quick notes to daily journal

Usage: bun thought.ts <message> [tags...]

Examples:
  bun thought.ts "Great idea for the app"
  bun thought.ts "Meeting notes" meeting work
  bun thought.ts "Remember to call mom" personal reminder

Output format:
  - HH:MM <message> #tag1 #tag2
`);
  process.exit(0);
}

const message = args[0];
const tags = args.slice(1);
const tagStr = tags.length ? " " + tags.map((t) => `#${t}`).join(" ") : "";
const entry = `- ${formatTime()} ${message}${tagStr}`;

await $`obsidian daily:append content=${entry} ${vaultArg}`.quiet();
console.log(`Added: ${entry}`);
