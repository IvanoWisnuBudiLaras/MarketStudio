import type { NextRequest } from "next/server";

const routes = {
  GET: /^workspaces(?:\/ws_[a-f0-9]{12}\/(?:offerings|worksheet|reports\/daily|ai-review\/config))?$/,
  PUT: /^workspaces\/ws_[a-f0-9]{12}\/worksheet$/,
  POST: /^(?:sessions|workspaces(?:\/ws_[a-f0-9]{12}\/(?:offerings|purchases|sales|reports\/daily\/ai-review))?)$/,
};
const noStore = { "Cache-Control": "no-store" };

function failure(status: number, code: string, message: string) {
  return Response.json({ code, message, field_errors: {}, request_id: crypto.randomUUID() }, { status, headers: noStore });
}

async function proxy(request: NextRequest, context: { params: Promise<{ route: string[] }> }) {
  const method = request.method as keyof typeof routes;
  const path = (await context.params).route.join("/");
  if (!routes[method]?.test(path)) return failure(404, "not_found", "Endpoint tidak ditemukan.");

  const port = process.env.MARKETSTUDIO_V3_API_PORT ?? "8101";
  if (!["development", "test"].includes(process.env.MARKETSTUDIO_ENV ?? "") ||
      !/^\d{1,5}$/.test(port) || Number(port) < 1 || Number(port) > 65535) {
    return failure(503, "configuration_error", "Konfigurasi API lokal tidak tersedia.");
  }

  const headers = new Headers();
  for (const name of ["authorization", "x-session-token", "idempotency-key", "content-type"]) {
    const value = request.headers.get(name);
    if (value !== null) headers.set(name, value);
  }

  let body: Uint8Array<ArrayBuffer> | undefined;
  if (method !== "GET" && request.body) {
    const reader = request.body.getReader();
    const limit = 1048576;
    const buffer = new Uint8Array(limit);
    let length = 0;
    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      if (length + value.byteLength > limit) {
        await reader.cancel();
        return failure(400, "invalid_content_length", "Ukuran body melebihi 1 MB.");
      }
      buffer.set(value, length);
      length += value.byteLength;
    }
    if (length) body = buffer.subarray(0, length);
  }

  try {
    const upstream = await fetch(
      `http://127.0.0.1:${port}/v1/${path}${request.nextUrl.search}`,
      { method, headers, body, redirect: "manual", cache: "no-store", signal: AbortSignal.timeout(15000) },
    );
    return new Response(upstream.body, {
      status: upstream.status,
      headers: { ...noStore, "Content-Type": upstream.headers.get("content-type") ?? "application/json" },
    });
  } catch {
    return failure(502, "upstream_unavailable", "API belum merespons. Coba lagi.");
  }
}

export const GET = proxy;
export const POST = proxy;
export const PUT = proxy;
