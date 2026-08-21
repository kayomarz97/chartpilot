import { NextResponse } from "next/server";

// TD-011 (secure variant): the backend Cloud Run service is PRIVATE
// (--no-allow-unauthenticated), so the browser cannot call it directly. This
// server-side route handler runs ON the frontend Cloud Run instance, mints a
// Google-signed OIDC identity token for its own service account (which holds
// roles/run.invoker on the backend) via the metadata server, and proxies the
// read-only run results. The browser only ever talks to this same-origin
// endpoint; the backend stays fully private.
//
// On ANY failure (no BACKEND_URL, no metadata server in local dev, backend
// unreachable, non-2xx) we return 502 with an empty body so the client falls
// back to bundled demo data — the site is never broken.

export const dynamic = "force-dynamic";

const RUN_ID = "demo";
const METADATA_IDENTITY_URL =
  "http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/identity";

function backendBaseUrl(): string | undefined {
  const url = process.env.BACKEND_URL;
  if (!url) return undefined;
  const trimmed = url.trim().replace(/\/+$/, "");
  return trimmed.length > 0 ? trimmed : undefined;
}

/** Mint an OIDC identity token (audience = backend URL) from the Cloud Run
 * metadata server. Returns null when not running on GCP (e.g. local dev). */
async function fetchIdentityToken(audience: string): Promise<string | null> {
  try {
    const res = await fetch(
      `${METADATA_IDENTITY_URL}?audience=${encodeURIComponent(audience)}`,
      { headers: { "Metadata-Flavor": "Google" }, cache: "no-store" },
    );
    if (!res.ok) return null;
    const token = (await res.text()).trim();
    return token.length > 0 ? token : null;
  } catch {
    return null;
  }
}

export async function GET() {
  const baseUrl = backendBaseUrl();
  if (!baseUrl) {
    return NextResponse.json({ error: "backend not configured" }, { status: 502 });
  }

  const token = await fetchIdentityToken(baseUrl);
  const headers: Record<string, string> = { Accept: "application/json" };
  if (token) headers.Authorization = `Bearer ${token}`;

  try {
    const upstream = await fetch(`${baseUrl}/runs/${RUN_ID}`, {
      headers,
      cache: "no-store",
    });
    if (!upstream.ok) {
      return NextResponse.json(
        { error: `backend ${upstream.status}` },
        { status: 502 },
      );
    }
    const data: unknown = await upstream.json();
    return NextResponse.json(data, { status: 200 });
  } catch {
    return NextResponse.json({ error: "backend unreachable" }, { status: 502 });
  }
}
