import { readFileSync, readdirSync } from "node:fs";
import { resolve, join, relative, basename } from "node:path";
import { createRequire } from "node:module";

const require = createRequire(resolve(process.cwd(), "package.json"));
const Gherkin = require("@cucumber/gherkin") as typeof import("@cucumber/gherkin");
const Messages = require("@cucumber/messages") as typeof import("@cucumber/messages");

type StepType = "given" | "when" | "then";

interface StepParam {
  name: string;
  type: string;
}

interface RawStep {
  keyword: StepType;
  text: string;
  pattern: string;
}

interface StepBucket {
  params: StepParam[];
  usedIn: Set<string>;
  count: number;
}

interface StepOutput {
  pattern: string;
  params: StepParam[];
  usedIn: string[];
  count: number;
}

interface FeatureOutput {
  file: string;
  name: string;
  scenarioCount: number;
  steps: string[];
}

interface MissingStep {
  pattern: string;
  params: StepParam[];
  definedIn: null;
}

interface DuplicateStep {
  pattern: string;
  definedIn: string[];
}

const STOP_WORDS = new Set([
  "the",
  "a",
  "an",
  "is",
  "in",
  "on",
  "at",
  "to",
  "for",
  "and",
  "or",
  "but",
  "should",
  "have",
  "has",
  "been",
  "be",
  "not",
]);

const uuidFn = Messages.IdGenerator.uuid();

function walkDir(dir: string, ext: string): string[] {
  const results: string[] = [];
  let entries: ReturnType<typeof readdirSync>;
  try {
    entries = readdirSync(dir, { withFileTypes: true });
  } catch {
    return results;
  }
  for (const entry of entries) {
    const fullPath = join(dir, entry.name);
    if (entry.isDirectory()) {
      results.push(...walkDir(fullPath, ext));
    } else if (entry.isFile() && entry.name.endsWith(ext)) {
      results.push(fullPath);
    }
  }
  return results;
}

function toPattern(text: string): string {
  let pat = text.replace(/<[^>]+>/g, "{string}");
  pat = pat.replace(/"[^"]*"/g, "{string}");
  pat = pat.replace(/(?<=^|\s)\d+\.\d+(?=\s|$)/g, "{float}");
  pat = pat.replace(/(?<=^|\s)\d+(?=\s|$)/g, "{int}");
  return pat;
}

function toCamelCase(str: string): string {
  const parts = str.split(/[\s_-]+/);
  return parts
    .map((p, i) => {
      if (i === 0) return p.toLowerCase();
      return p.charAt(0).toUpperCase() + p.slice(1).toLowerCase();
    })
    .join("");
}

function deriveParamName(pattern: string, matchPos: number, idx: number, type: string): string {
  const before = pattern.slice(0, matchPos).trim();
  const wordsBeforeAll = before.split(/\s+/);
  const lastWords = wordsBeforeAll.slice(-3);
  const joined = lastWords.join(" ");

  const asTheMatch = joined.match(/as\s+the\s+(\w+)$/i);
  if (asTheMatch) return toCamelCase(asTheMatch[1]);

  const prepMatch = joined.match(/(?:with|for|to|from|of|indicating the)\s+(\w[\w\s]*?)$/i);
  if (prepMatch) return toCamelCase(prepMatch[1].trim());

  const wordBefore = wordsBeforeAll[wordsBeforeAll.length - 1];
  if (wordBefore && /^[a-zA-Z]+$/.test(wordBefore) && !STOP_WORDS.has(wordBefore.toLowerCase())) {
    return toCamelCase(wordBefore);
  }

  const afterStr = pattern.slice(matchPos + type.length + 2).trim();
  const wordsAfter = afterStr.split(/\s+/);
  if (
    wordsAfter[0] &&
    /^[a-zA-Z]+$/.test(wordsAfter[0]) &&
    !STOP_WORDS.has(wordsAfter[0].toLowerCase())
  ) {
    return toCamelCase(wordsAfter[0]);
  }

  return type + (idx > 0 ? idx : "");
}

function extractParams(pattern: string): StepParam[] {
  const params: StepParam[] = [];
  const re = /\{(string|int|float)\}/g;
  let m: RegExpExecArray | null;
  let idx = 0;
  while ((m = re.exec(pattern)) !== null) {
    params.push({ name: deriveParamName(pattern, m.index, idx, m[1]), type: m[1] });
    idx++;
  }
  return params;
}

function resolveKeyword(keyword: string, lastPrimary: StepType | null): StepType {
  const kw = keyword.trim().toLowerCase();
  if (kw === "given") return "given";
  if (kw === "when") return "when";
  if (kw === "then") return "then";
  return lastPrimary ?? "given";
}

function extractStepsFromScenario(steps: { keyword: string; text: string }[]): RawStep[] {
  const result: RawStep[] = [];
  let lastPrimary: StepType | null = null;

  for (const step of steps) {
    const keyword = resolveKeyword(step.keyword, lastPrimary);
    const kw = step.keyword.trim().toLowerCase();
    if (kw === "given" || kw === "when" || kw === "then") {
      lastPrimary = keyword;
    }
    result.push({ keyword, text: step.text, pattern: toPattern(step.text) });
  }

  return result;
}

interface GherkinFeature {
  name: string;
  children: GherkinChild[];
}

interface GherkinChild {
  background?: { steps: { keyword: string; text: string }[] };
  scenario?: {
    steps: { keyword: string; text: string }[];
    examples: { tableBody: unknown[] }[];
  };
  rule?: { children: GherkinChild[] };
}

function countScenariosFromAST(feature: GherkinFeature): number {
  let count = 0;

  function processChildren(children: GherkinChild[]) {
    for (const child of children) {
      if (child.background) continue;
      if (child.scenario) {
        const { examples } = child.scenario;
        if (examples?.length > 0) {
          for (const ex of examples) count += ex.tableBody.length;
        } else {
          count++;
        }
      }
      if (child.rule) processChildren(child.rule.children);
    }
  }

  processChildren(feature.children);
  return count;
}

function parseFeatureFile(
  filePath: string,
  basePath: string,
): {
  relativePath: string;
  featureName: string;
  scenarioCount: number;
  rawSteps: RawStep[];
} | null {
  const content = readFileSync(filePath, "utf8");
  const relativePath = relative(basePath, filePath);

  const builder = new Gherkin.AstBuilder(uuidFn);
  const matcher = new Gherkin.GherkinClassicTokenMatcher();
  const parser = new Gherkin.Parser(builder, matcher);

  let gherkinDocument: { feature?: GherkinFeature };
  try {
    gherkinDocument = parser.parse(content);
  } catch (e) {
    console.error(`Failed to parse ${relativePath}: ${(e as Error).message}`);
    return null;
  }

  const feature = gherkinDocument.feature;
  if (!feature) return null;

  const rawSteps: RawStep[] = [];
  let backgroundSteps: RawStep[] = [];

  function processChildren(children: GherkinChild[]) {
    for (const child of children) {
      if (child.background) {
        backgroundSteps = extractStepsFromScenario(child.background.steps);
      }
      if (child.scenario) {
        rawSteps.push(...extractStepsFromScenario(child.scenario.steps));
      }
      if (child.rule) processChildren(child.rule.children);
    }
  }

  processChildren(feature.children);
  rawSteps.push(...backgroundSteps);

  return {
    relativePath,
    featureName: feature.name,
    scenarioCount: countScenariosFromAST(feature),
    rawSteps,
  };
}

function escapeRegex(str: string): string {
  return str.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function scanStepDefinitions(dir: string): { type: StepType; pattern: string; file: string }[] {
  const files = walkDir(dir, ".js");
  const defs: { type: StepType; pattern: string; file: string }[] = [];

  for (const filePath of files) {
    const content = readFileSync(filePath, "utf8");
    const fileName = basename(filePath);
    const re = /\b(Given|When|Then)\s*\(\s*(['"`])((?:(?!\2)[^\\]|\\.)*)\2/g;
    let m: RegExpExecArray | null;
    while ((m = re.exec(content)) !== null) {
      const type = m[1].toLowerCase() as StepType;
      const quote = m[2];
      const pattern = m[3].replace(new RegExp("\\\\(" + escapeRegex(quote) + ")", "g"), "$1");
      defs.push({ type, pattern, file: fileName });
    }
  }

  return defs;
}

function main() {
  const args = process.argv.slice(2);
  if (args.length === 0) {
    console.error("Usage: npx tsx extract_steps.ts <features-dir> [--check <step-defs-dir>]");
    process.exit(1);
  }

  const featuresDir = resolve(args[0]);
  const checkIdx = args.indexOf("--check");
  const checkDir = checkIdx !== -1 && args[checkIdx + 1] ? resolve(args[checkIdx + 1]) : null;

  const featureFiles = walkDir(featuresDir, ".feature");
  if (featureFiles.length === 0) {
    console.error(`No .feature files found in ${featuresDir}`);
    process.exit(1);
  }

  const features: FeatureOutput[] = [];
  const stepsByType: Record<StepType, Record<string, StepBucket>> = {
    given: {},
    when: {},
    then: {},
  };

  for (const file of featureFiles) {
    const parsed = parseFeatureFile(file, featuresDir);
    if (!parsed) continue;

    const featureStepPatterns = new Set<string>();
    for (const step of parsed.rawSteps) {
      featureStepPatterns.add(step.pattern);
      const bucket = stepsByType[step.keyword];
      if (!bucket[step.pattern]) {
        bucket[step.pattern] = {
          params: extractParams(step.pattern),
          usedIn: new Set(),
          count: 0,
        };
      }
      bucket[step.pattern].usedIn.add(parsed.relativePath);
      bucket[step.pattern].count++;
    }

    features.push({
      file: parsed.relativePath,
      name: parsed.featureName,
      scenarioCount: parsed.scenarioCount,
      steps: [...featureStepPatterns],
    });
  }

  const stepsOutput: Record<StepType, StepOutput[]> = { given: [], when: [], then: [] };
  const uniqueCounts: Record<string, number> = {};
  let totalScenarios = 0;

  for (const type of ["given", "when", "then"] as const) {
    stepsOutput[type] = Object.entries(stepsByType[type])
      .sort(([, a], [, b]) => b.count - a.count)
      .map(([pattern, data]) => ({
        pattern,
        params: data.params,
        usedIn: [...data.usedIn].sort(),
        count: data.count,
      }));
    uniqueCounts[type] = stepsOutput[type].length;
  }

  for (const f of features) totalScenarios += f.scenarioCount;

  const output: Record<string, unknown> = {
    features,
    steps: stepsOutput,
    summary: { totalFeatures: features.length, totalScenarios, uniqueSteps: uniqueCounts },
  };

  if (checkDir) {
    const defs = scanStepDefinitions(checkDir);
    const definedByType: Record<StepType, Record<string, string[]>> = {
      given: {},
      when: {},
      then: {},
    };
    for (const def of defs) {
      if (!definedByType[def.type][def.pattern]) {
        definedByType[def.type][def.pattern] = [];
      }
      definedByType[def.type][def.pattern].push(def.file);
    }

    const missing: Record<StepType, MissingStep[]> = { given: [], when: [], then: [] };
    for (const type of ["given", "when", "then"] as const) {
      for (const step of stepsOutput[type]) {
        if (!definedByType[type][step.pattern]) {
          missing[type].push({ pattern: step.pattern, params: step.params, definedIn: null });
        }
      }
    }

    const allDefsByPattern: Record<string, Set<string>> = {};
    for (const def of defs) {
      if (!allDefsByPattern[def.pattern]) allDefsByPattern[def.pattern] = new Set();
      allDefsByPattern[def.pattern].add(def.file);
    }
    const duplicates: DuplicateStep[] = [];
    for (const [pattern, files] of Object.entries(allDefsByPattern)) {
      if (files.size > 1) duplicates.push({ pattern, definedIn: [...files].sort() });
    }

    output.missing = missing;
    output.duplicates = duplicates;
  }

  console.log(JSON.stringify(output, null, 2));
}

main();
