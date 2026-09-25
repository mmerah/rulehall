async function fetchJson(url) {
  const response = await fetch(url);
  if (response.status !== 200) {
    console.error(`${response.status} ${url}`);
    process.exit(1);
  }
  return response.json();
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

module.exports = { fetchJson, pool };
