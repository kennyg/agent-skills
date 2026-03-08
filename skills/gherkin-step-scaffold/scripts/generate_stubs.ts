import { readFileSync, writeFileSync, mkdirSync } from "node:fs";
import { resolve, join, basename } from "node:path";

interface StepParam {
  name: string;
  type: string;
}

interface StepOutput {
  pattern: string;
  params: StepParam[];
  usedIn: string[];
  count: number;
}

type StepType = "given" | "when" | "then";

const STEP_TYPES: readonly StepType[] = ["given", "when", "then"] as const;

interface ExtractOutput {
  features: { file: string; name: string; scenarioCount: number; steps: string[] }[];
  steps: Record<StepType, StepOutput[]>;
  summary: { totalFeatures: number; totalScenarios: number; uniqueSteps: Record<string, number> };
}

type StubGroup = Record<StepType, StepOutput[]>;

function topicFromFeatureFile(file: string): string {
  return basename(file, ".feature");
}

function tsType(paramType: string): string {
  if (paramType === "int" || paramType === "float") return "number";
  return "string";
}

function stubGroupCount(group: StubGroup): number {
  return group.given.length + group.when.length + group.then.length;
}

function generateStubFile(group: StubGroup, typescript: boolean): string {
  const lines: string[] = [];

  if (typescript) {
    lines.push(`import { Given, When, Then } from "@cucumber/cucumber";`);
  } else {
    lines.push(`const { Given, When, Then } = require('@cucumber/cucumber');`);
  }

  for (const type of STEP_TYPES) {
    const steps = group[type];
    if (steps.length === 0) continue;

    const keyword = type.charAt(0).toUpperCase() + type.slice(1);
    lines.push("");
    lines.push(`// --- ${keyword} Steps ---`);

    for (const step of steps) {
      lines.push("");
      const params = step.params
        .map((p) => (typescript ? `${p.name}: ${tsType(p.type)}` : p.name))
        .join(", ");
      lines.push(`${keyword}('${step.pattern.replace(/'/g, "\\'")}', function (${params}) {`);
      lines.push(`  return 'pending';`);
      lines.push(`});`);
    }
  }

  lines.push("");
  return lines.join("\n");
}

function main() {
  const args = process.argv.slice(2);
  const tsFlag = args.includes("--ts");
  const filteredArgs = args.filter((a) => a !== "--ts");

  if (filteredArgs.length < 1) {
    console.error(
      "Usage: npx tsx extract_steps.ts <features-dir> | npx tsx generate_stubs.ts <output-dir> [--ts]",
    );
    process.exit(1);
  }

  const outputDir = resolve(filteredArgs[0]);
  const input = readFileSync("/dev/stdin", "utf-8");
  const data: ExtractOutput = JSON.parse(input);

  const topicGroups = new Map<string, StubGroup>();
  const commonGroup: StubGroup = { given: [], when: [], then: [] };

  for (const type of STEP_TYPES) {
    for (const step of data.steps[type]) {
      if (step.usedIn.length > 1) {
        commonGroup[type].push(step);
      } else if (step.usedIn.length === 1) {
        const topic = topicFromFeatureFile(step.usedIn[0]);
        if (!topicGroups.has(topic)) {
          topicGroups.set(topic, { given: [], when: [], then: [] });
        }
        topicGroups.get(topic)![type].push(step);
      }
    }
  }

  mkdirSync(outputDir, { recursive: true });

  const ext = tsFlag ? ".ts" : ".js";
  const generated: { file: string; steps: number }[] = [];

  for (const [topic, group] of topicGroups) {
    const stepCount = stubGroupCount(group);
    if (stepCount === 0) continue;

    const fileName = `${topic}_steps${ext}`;
    writeFileSync(join(outputDir, fileName), generateStubFile(group, tsFlag));
    generated.push({ file: fileName, steps: stepCount });
  }

  const commonCount = stubGroupCount(commonGroup);
  if (commonCount > 0) {
    const fileName = `common_steps${ext}`;
    writeFileSync(join(outputDir, fileName), generateStubFile(commonGroup, tsFlag));
    generated.push({ file: fileName, steps: commonCount });
  }

  const summary = {
    outputDir,
    files: generated,
    totalFiles: generated.length,
    totalSteps: generated.reduce((sum, g) => sum + g.steps, 0),
    format: tsFlag ? "TypeScript" : "JavaScript",
  };
  console.log(JSON.stringify(summary, null, 2));
}

main();
