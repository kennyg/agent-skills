import { readFileSync, readdirSync, existsSync, statSync } from "node:fs";
import { resolve, join } from "node:path";

interface Heading {
  level: number;
  sectionNum: string | null;
  name: string;
  tag: string | null;
  lineIndex: number;
}

interface Section {
  sectionNum: string | null;
  name: string;
  tag: string;
  shallCount: number;
  shallStatements: string[];
  scenarioCount: number;
}

type Status = "covered" | "low" | "missing";

const TAG_RE = /\[(ADDED|CHANGED|REMOVED)\]/;
const HEADING_RE = /^(#{2,3})\s+(.+)$/;
const SECTION_NUM_RE = /^(\d+(?:\.\d+)?)/;
const SHALL_RE = /\bSHALL\b/;
const SPEC_REF_RE = /^\s*#\s*Spec ref:\s*Section\s+([\d.]+)/;
const SCENARIO_RE = /^\s*(Scenario|Scenario Outline):/;

function findFeatureFiles(dir: string): string[] {
  const results: string[] = [];
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    const fullPath = join(dir, entry.name);
    if (entry.isDirectory()) results.push(...findFeatureFiles(fullPath));
    else if (entry.name.endsWith(".feature")) results.push(fullPath);
  }
  return results;
}

function getStatus(shallCount: number, scenarioCount: number): Status {
  if (scenarioCount === 0) return "missing";
  if (scenarioCount < shallCount / 3) return "low";
  return "covered";
}

const STATUS_LABELS: Record<Status, string> = {
  covered: "\u2713 Covered",
  low: "\u26A0 Low coverage",
  missing: "\u2717 Missing",
};

function pad(str: string, width: number): string {
  return str + " ".repeat(Math.max(0, width - str.length));
}

function padNum(num: number, width: number): string {
  const s = String(num);
  return " ".repeat(Math.max(0, width - s.length)) + s;
}

function main() {
  const args = process.argv.slice(2);
  if (args.length < 2) {
    console.error("Usage: npx tsx validate_traceability.ts <spec-path> <features-dir>");
    process.exit(1);
  }

  const specPath = resolve(args[0]);
  const featuresDir = resolve(args[1]);

  if (!existsSync(specPath)) {
    console.error(`Spec file not found: ${specPath}`);
    process.exit(1);
  }
  if (!existsSync(featuresDir) || !statSync(featuresDir).isDirectory()) {
    console.error(`Features directory not found: ${featuresDir}`);
    process.exit(1);
  }

  const specLines = readFileSync(specPath, "utf-8").split("\n");

  let specTitle = "Specification";
  for (const line of specLines) {
    const m = line.match(/^#\s+(.+)$/);
    if (m) {
      specTitle = m[1].trim();
      break;
    }
  }

  const headings: Heading[] = [];
  for (let i = 0; i < specLines.length; i++) {
    const hm = specLines[i].match(HEADING_RE);
    if (hm) {
      const level = hm[1].length;
      const text = hm[2].trim();
      const tagMatch = text.match(TAG_RE);
      const numMatch = text.match(SECTION_NUM_RE);
      headings.push({
        level,
        sectionNum: numMatch?.[1] ?? null,
        name: text
          .replace(TAG_RE, "")
          .replace(/^\d+(?:\.\d+)?\s*\.?\s*/, "")
          .trim(),
        tag: tagMatch?.[1] ?? null,
        lineIndex: i,
      });
    }
  }

  const sections: Section[] = [];
  for (let h = 0; h < headings.length; h++) {
    const heading = headings[h];
    if (!heading.tag) continue;

    if (heading.level === 2) {
      let hasTaggedChildren = false;
      for (let j = h + 1; j < headings.length; j++) {
        if (headings[j].level === 2) break;
        if (headings[j].level === 3 && headings[j].tag) {
          hasTaggedChildren = true;
          break;
        }
      }
      if (hasTaggedChildren) continue;
    }

    const startLine = heading.lineIndex;
    let endLine = specLines.length;
    for (let j = h + 1; j < headings.length; j++) {
      endLine = headings[j].lineIndex;
      break;
    }

    const shallStatements: string[] = [];
    for (let i = startLine + 1; i < endLine; i++) {
      if (SHALL_RE.test(specLines[i])) {
        shallStatements.push(specLines[i].trim().replace(/^-\s*/, ""));
      }
    }

    sections.push({
      sectionNum: heading.sectionNum,
      name: heading.name,
      tag: heading.tag,
      shallCount: shallStatements.length,
      shallStatements,
      scenarioCount: 0,
    });
  }

  const featureFiles = findFeatureFiles(featuresDir);
  let totalScenarios = 0;

  for (const filePath of featureFiles) {
    const lines = readFileSync(filePath, "utf-8").split("\n");
    let currentRefs: string[] = [];
    let seenScenarioSinceLastRef = false;

    for (const line of lines) {
      const refMatch = line.match(SPEC_REF_RE);
      if (refMatch) {
        if (seenScenarioSinceLastRef || currentRefs.length === 0) {
          currentRefs = [];
          seenScenarioSinceLastRef = false;
        }
        currentRefs.push(refMatch[1]);
        continue;
      }
      if (SCENARIO_RE.test(line)) {
        totalScenarios++;
        seenScenarioSinceLastRef = true;
        for (const num of currentRefs) {
          const section = sections.find((s) => s.sectionNum === num);
          if (section) section.scenarioCount++;
        }
      }
    }
  }

  const wSection = Math.max(
    "Section".length,
    ...sections.map((s) => `${s.sectionNum} ${s.name}`.length),
  );
  const wTag = Math.max("Tag".length, ...sections.map((s) => s.tag.length));
  const wShalls = Math.max("SHALLs".length, 4);
  const wScenarios = Math.max("Scenarios".length, 4);
  const wStatus = Math.max("Status".length, 16);
  const totalWidth = wSection + 2 + wTag + 2 + wShalls + 2 + wScenarios + 2 + wStatus;

  console.log(`Traceability Report: ${specTitle}`);
  console.log("\u2550".repeat(totalWidth));
  console.log();
  console.log(
    `${pad("Section", wSection)}  ${pad("Tag", wTag)}  ${pad("SHALLs", wShalls)}  ${pad("Scenarios", wScenarios)}  Status`,
  );
  console.log("\u2500".repeat(totalWidth));

  for (const s of sections) {
    const label = `${s.sectionNum} ${s.name}`;
    const status = getStatus(s.shallCount, s.scenarioCount);
    console.log(
      `${pad(label, wSection)}  ${pad(s.tag, wTag)}  ${padNum(s.shallCount, wShalls)}  ${padNum(s.scenarioCount, wScenarios)}  ${STATUS_LABELS[status]}`,
    );
  }

  const coveredCount = sections.filter(
    (s) => getStatus(s.shallCount, s.scenarioCount) === "covered",
  ).length;
  const lowCount = sections.filter(
    (s) => getStatus(s.shallCount, s.scenarioCount) === "low",
  ).length;
  const missingCount = sections.filter(
    (s) => getStatus(s.shallCount, s.scenarioCount) === "missing",
  ).length;
  const totalShalls = sections.reduce((sum, s) => sum + s.shallCount, 0);

  console.log();
  console.log("Summary:");
  console.log(
    `  Sections: ${sections.length} total, ${coveredCount} covered, ${lowCount} low coverage, ${missingCount} missing`,
  );
  console.log(`  SHALL statements: ${totalShalls} total across all sections`);
  console.log(`  Scenarios: ${totalScenarios} total across all features`);

  const missingSections = sections.filter(
    (s) => getStatus(s.shallCount, s.scenarioCount) === "missing",
  );
  if (missingSections.length > 0) {
    console.log();
    console.log("Missing coverage:");
    for (const s of missingSections) {
      console.log(
        `  - Section ${s.sectionNum} "${s.name}" has ${s.shallCount} SHALL statements but no scenarios`,
      );
      for (const stmt of s.shallStatements) {
        console.log(`    SHALL: ${stmt}`);
      }
    }
  }
}

main();
