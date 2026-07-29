import { readdir, readFile } from "node:fs/promises";
import path from "node:path";

const root = path.resolve("src");
const targets = [];
const forbidden = [
  { pattern: /<<<<<<<|=======|>>>>>>>/, label: "merge conflict marker" },
  { pattern: /\bsession_token\b/, label: "raw session_token reference in frontend" },
];

async function walk(dir) {
  const entries = await readdir(dir, { withFileTypes: true });
  for (const entry of entries) {
    const fullPath = path.join(dir, entry.name);
    if (entry.isDirectory()) {
      await walk(fullPath);
      continue;
    }
    if (/\.(js|jsx)$/.test(entry.name)) {
      targets.push(fullPath);
    }
  }
}

await walk(root);

const failures = [];
for (const file of targets) {
  const text = await readFile(file, "utf8");
  const lines = text.split(/\r?\n/);
  lines.forEach((line, index) => {
    if (/\s+$/.test(line)) {
      failures.push(`${file}:${index + 1} trailing whitespace`);
    }
    for (const rule of forbidden) {
      if (rule.pattern.test(line)) {
        failures.push(`${file}:${index + 1} ${rule.label}`);
      }
    }
  });
}

if (failures.length) {
  console.error(failures.join("\n"));
  process.exit(1);
}

console.log(`lint-basic passed (${targets.length} files)`);
