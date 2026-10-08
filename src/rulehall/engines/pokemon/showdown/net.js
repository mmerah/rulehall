const fs = require("fs");
const path = require("path");

const USER_AGENT = "rulehall-champions/0 (free local non-commercial game)";

async function fetchText(url, headers = {}) {
  const response = await fetch(url, { headers });
  if (response.status !== 200) {
    console.error(`${response.status} ${url}`);
    process.exit(1);
  }
  return response.text();
}

async function fetchJson(url) {
  return JSON.parse(await fetchText(url));
}

async function cachedText(url, cachePath, headers, beforeFetch = async () => {}) {
  if (fs.existsSync(cachePath)) return fs.readFileSync(cachePath, "utf8");
  await beforeFetch();
  console.error(`GET ${url}`);
  const text = await fetchText(url, headers);
  fs.mkdirSync(path.dirname(cachePath), { recursive: true });
  fs.writeFileSync(cachePath, text);
  return text;
}

async function pool(items, worker, width = 8) {
  const results = new Array(items.length);
  let next = 0;
  const run = async () => {
    while (next < items.length) {
      const index = next++;
      results[index] = await worker(items[index]);
    }
  };
  await Promise.all(Array.from({ length: width }, run));
  return results;
}

function compare(a, b) {
  return a < b ? -1 : a > b ? 1 : 0;
}

function fail(message) {
  throw new Error(message);
}

module.exports = { USER_AGENT, cachedText, compare, fail, fetchJson, fetchText, pool };
