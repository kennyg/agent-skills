import { readFileSync, existsSync } from "node:fs";
import { resolve } from "node:path";
import { createRequire } from "node:module";

const require = createRequire(resolve(process.cwd(), "package.json"));
const MarkdownIt = require("markdown-it") as typeof import("markdown-it");

type Token = ReturnType<InstanceType<typeof MarkdownIt>["parse"]>[number];

interface ShallStatement {
  text: string;
  quotedStrings: string[];
}

interface SpecSection {
  shall: ShallStatement[];
  shallNot: ShallStatement[];
  lists: string[][];
  prose: string[];
  number: string | null;
  title: string;
  tag: string | null;
  level: number;
  parentNumber: string | null;
}

interface ParsedSpec {
  title: string;
  sections: SpecSection[];
}

const md = new MarkdownIt();

function inlineText(token: Token): string {
  if (!token.children) return token.content || "";
  return token.children
    .filter((c) => c.type === "text" || c.type === "code_inline" || c.type === "softbreak")
    .map((c) => (c.type === "softbreak" ? " " : c.content))
    .join("");
}

function extractQuotedStrings(text: string): string[] {
  const quoted: string[] = [];
  const regex = /\u201c([^\u201d]*)\u201d|"([^"]*?)"/g;
  let match: RegExpExecArray | null;
  while ((match = regex.exec(text)) !== null) {
    quoted.push(match[1] || match[2]);
  }
  return quoted;
}

function hasShallNot(text: string): boolean {
  return /SHALL\s+NOT/i.test(text);
}

function hasShall(text: string): boolean {
  if (!/SHALL/i.test(text)) return false;
  const withoutShallNot = text.replace(/SHALL\s+NOT/gi, "");
  return /SHALL/i.test(withoutShallNot);
}

function parseSpec(filePath: string): ParsedSpec {
  const content = readFileSync(filePath, "utf-8");
  const tokens = md.parse(content, {});

  let title = "";
  const sections: SpecSection[] = [];
  let i = 0;

  while (i < tokens.length) {
    const token = tokens[i];

    if (token.type === "heading_open" && token.tag === "h1") {
      const inlineToken = tokens[i + 1];
      if (inlineToken?.type === "inline") {
        title = inlineText(inlineToken);
      }
      i += 3;
      continue;
    }

    if (token.type === "heading_open" && (token.tag === "h2" || token.tag === "h3")) {
      const level = token.tag === "h2" ? 2 : 3;
      const inlineToken = tokens[i + 1];
      const rawHeading = inlineToken ? inlineText(inlineToken) : "";
      i += 3;

      let tag: string | null = null;
      const tagMatch = rawHeading.match(/\[(ADDED|CHANGED|REMOVED)\]\s*$/);
      if (tagMatch) tag = tagMatch[1];

      const headingWithoutTag = rawHeading.replace(/\s*\[(ADDED|CHANGED|REMOVED)\]\s*$/, "").trim();

      let number: string | null = null;
      let sectionTitle = headingWithoutTag;
      const numberMatch = headingWithoutTag.match(/^(\d+(?:\.\d+)*)\s+(.+)$/);
      if (numberMatch) {
        number = numberMatch[1];
        sectionTitle = numberMatch[2].trim();
      }

      let parentNumber: string | null = null;
      if (number) {
        const parts = number.split(".");
        if (parts.length > 1) {
          parentNumber = parts.slice(0, -1).join(".");
        }
      }

      const shall: ShallStatement[] = [];
      const shallNot: ShallStatement[] = [];
      const lists: string[][] = [];
      const prose: string[] = [];

      while (i < tokens.length) {
        const bt = tokens[i];
        if (bt.type === "heading_open") break;

        if (bt.type === "paragraph_open") {
          const pInline = tokens[i + 1];
          if (pInline?.type === "inline") {
            const text = inlineText(pInline);
            if (hasShallNot(text) && !hasShall(text)) {
              shallNot.push({ text, quotedStrings: extractQuotedStrings(text) });
            } else if (hasShall(text)) {
              shall.push({ text, quotedStrings: extractQuotedStrings(text) });
            } else if (text.trim()) {
              prose.push(text);
            }
          }
          i += 3;
          continue;
        }

        if (bt.type === "bullet_list_open") {
          const currentList: string[] = [];
          i++;
          while (i < tokens.length && tokens[i].type !== "bullet_list_close") {
            if (tokens[i].type === "list_item_open") {
              i++;
              let itemText = "";
              while (i < tokens.length && tokens[i].type !== "list_item_close") {
                if (tokens[i].type === "inline") {
                  itemText += inlineText(tokens[i]);
                }
                i++;
              }
              if (itemText) currentList.push(itemText);
              if (i < tokens.length) i++;
            } else {
              i++;
            }
          }
          if (i < tokens.length) i++;
          if (currentList.length > 0) lists.push(currentList);
          continue;
        }

        i++;
      }

      sections.push({
        shall,
        shallNot,
        lists,
        prose,
        number,
        title: sectionTitle,
        tag,
        level,
        parentNumber,
      });
      continue;
    }

    i++;
  }

  return { title, sections };
}

const args = process.argv.slice(2);
if (args.length < 1) {
  console.error("Usage: npx tsx parse_spec.ts <path-to-spec.md>");
  process.exit(1);
}

const filePath = resolve(args[0]);
if (!existsSync(filePath)) {
  console.error(`File not found: ${filePath}`);
  process.exit(1);
}

console.log(JSON.stringify(parseSpec(filePath), null, 2));
