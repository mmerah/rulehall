const { toID } = require("pokemon-showdown");
const { BO3_SUFFIX, FORMAT_PREFIX } = require("./champions-legal");
const { fail, fetchText } = require("./net");

const FORMATS_URL = "https://raw.githubusercontent.com/smogon/pokemon-showdown";

// Prints the Champions VGC format ids of commit `next` that commit `pinned` lacks, one per line.
async function main() {
  const [pinned, next] = process.argv.slice(2);
  if (next === undefined) fail("usage: node champions-formats.js <pinned commit> <next commit>");
  const pinnedIds = await championsFormatIdsAt(pinned);
  for (const formatId of await championsFormatIdsAt(next)) {
    if (!pinnedIds.includes(formatId)) console.log(formatId);
  }
}

async function championsFormatIdsAt(commit) {
  const source = await fetchText(`${FORMATS_URL}/${commit}/config/formats.ts`);
  return [...source.matchAll(/^\s*name: "(.+)",$/gm)]
    .map(([, name]) => toID(name))
    .filter((formatId) => formatId.startsWith(FORMAT_PREFIX) && !formatId.endsWith(BO3_SUFFIX));
}

main();
