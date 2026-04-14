export async function jget(url) {
  const resp = await fetch(url);
  return await resp.json();
}

export async function jpost(url, body) {
  const resp = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  return await resp.json();
}
