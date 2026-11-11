// Cloudflare Worker: bewaart welke browsers meldingen van de vissenlijst willen ontvangen.
// Het versturen zelf doet de GitHub Action (scrape.py); die haalt hier de lijst op.
//
// Nodig in Cloudflare (Settings van deze Worker):
//   - KV-binding met de naam  SUBS
//   - secret   ADMIN_TOKEN     (zelfde waarde als het GitHub-secret PUSH_ADMIN_TOKEN)
//   - variable ALLOWED_ORIGIN  https://timdieters.github.io

const MAX_AANMELDINGEN = 500;

async function sleutel(endpoint) {
  const hash = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(endpoint));
  return [...new Uint8Array(hash)].map(b => b.toString(16).padStart(2, "0")).join("");
}

function geldig(sub) {
  return sub && typeof sub.endpoint === "string" && sub.endpoint.startsWith("https://") && sub.endpoint.length < 1000 &&
    sub.keys && typeof sub.keys.p256dh === "string" && typeof sub.keys.auth === "string" &&
    sub.keys.p256dh.length < 200 && sub.keys.auth.length < 100;
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    const origin = request.headers.get("Origin") || "";
    const toegestaan = env.ALLOWED_ORIGIN || "https://timdieters.github.io";
    const cors = {
      "Access-Control-Allow-Origin": toegestaan,
      "Access-Control-Allow-Methods": "POST, OPTIONS",
      "Access-Control-Allow-Headers": "Content-Type",
      "Vary": "Origin",
    };
    const antwoord = (data, status = 200) =>
      new Response(JSON.stringify(data), {status, headers: {"Content-Type": "application/json", ...cors}});

    if (request.method === "OPTIONS") return new Response(null, {status: 204, headers: cors});

    // ---- voor de site: aan- en afmelden
    if (request.method === "POST" && (url.pathname === "/subscribe" || url.pathname === "/unsubscribe")) {
      if (origin !== toegestaan) return antwoord({fout: "niet toegestaan"}, 403);
      let body;
      try { body = await request.json(); } catch (e) { return antwoord({fout: "ongeldige invoer"}, 400); }

      if (url.pathname === "/unsubscribe") {
        if (typeof body.endpoint !== "string") return antwoord({fout: "ongeldige invoer"}, 400);
        await env.SUBS.delete(await sleutel(body.endpoint));
        return antwoord({ok: true});
      }
      if (!geldig(body)) return antwoord({fout: "ongeldige aanmelding"}, 400);
      const bestaand = await env.SUBS.list({limit: 1000});
      if (bestaand.keys.length >= MAX_AANMELDINGEN) return antwoord({fout: "vol"}, 507);
      await env.SUBS.put(await sleutel(body.endpoint),
        JSON.stringify({endpoint: body.endpoint, keys: {p256dh: body.keys.p256dh, auth: body.keys.auth}}));
      return antwoord({ok: true}, 201);
    }

    // ---- voor de GitHub Action: lijst ophalen en verlopen aanmeldingen opruimen
    if (url.pathname === "/list" || url.pathname === "/remove") {
      if (!env.ADMIN_TOKEN || request.headers.get("Authorization") !== "Bearer " + env.ADMIN_TOKEN)
        return antwoord({fout: "geen toegang"}, 401);

      if (url.pathname === "/list" && request.method === "GET") {
        const {keys} = await env.SUBS.list({limit: 1000});
        const subs = await Promise.all(keys.map(k => env.SUBS.get(k.name, "json")));
        return antwoord(subs.filter(Boolean));
      }
      if (url.pathname === "/remove" && request.method === "POST") {
        const {endpoints = []} = await request.json();
        await Promise.all(endpoints.map(async e => env.SUBS.delete(await sleutel(e))));
        return antwoord({ok: true, verwijderd: endpoints.length});
      }
    }
    return antwoord({fout: "niet gevonden"}, 404);
  },
};
