import { NextResponse } from "next/server";

// Phase B (spec §53): the backend Cloud Run service is PRIVATE
// (--no-allow-unauthenticated) except the one public read (`GET
// /runs/{run_id}`, see `app/api/runs/route.ts`). This route mints a
// Google-signed OIDC identity token for its own service account (which
// holds roles/run.invoker on the backend) via the metadata server, and
// proxies ONE clinician label (CONFIRM/OVERRIDE/CORRECT + an optional
// note) to the backend's OIDC-protected
// `POST /runs/{run_id}/patients/{patientId}/clinician-action`. The browser
// only ever talks to this same-origin endpoint; the backend stays fully
// private.
//
// On ANY failure (no BACKEND_URL, no metadata server in local dev, backend
// unreachable, non-2xx, malformed body) we return a non-2xx response so the
// caller can show an inline "couldn't save" state — never throws, never
// crashes the page.

export const dynamic = "force-dynamic";

const RUN_ID = "demo";
const METADATA_IDENTITY_URL =
  "http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/identity";

interface ClinicianActionBody {
  patientId: string;
  claimId: string;
  action: "CONFIRM" | "OVERRIDE" | "CORRECT";
  note?: string;
  verdictShown?: string | null;
  actionId: string;
}

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

function isValidBody(body: unknown): body is ClinicianActionBody {
  if (typeof body !== "object" || body === null) return false;
  const b = body as Record<string, unknown>;
  return (
    typeof b.patientId === "string" &&
    b.patientId.length > 0 &&
    typeof b.claimId === "string" &&
    b.claimId.length > 0 &&
    (b.action === "CONFIRM" || b.action === "OVERRIDE" || b.action === "CORRECT") &&
    typeof b.actionId === "string" &&
    b.actionId.length > 0 &&
    (b.note === undefined || typeof b.note === "string") &&
    (b.verdictShown === undefined || b.verdictShown === null || typeof b.verdictShown === "string")
  );
}

export async function POST(request: Request) {
  const baseUrl = backendBaseUrl();
  if (!baseUrl) {
    return NextResponse.json({ error: "backend not configured" }, { status: 502 });
  }

  let body: unknown;
  try {
    body = await request.json();
  } catch {
    return NextResponse.json({ error: "invalid JSON body" }, { status: 400 });
  }
  if (!isValidBody(body)) {
    return NextResponse.json({ error: "invalid clinician action body" }, { status: 400 });
  }

  const token = await fetchIdentityToken(baseUrl);
  const headers: Record<string, string> = {
    Accept: "application/json",
    "Content-Type": "application/json",
  };
  if (token) headers.Authorization = `Bearer ${token}`;

  try {
    const upstream = await fetch(
      `${baseUrl}/runs/${RUN_ID}/patients/${encodeURIComponent(body.patientId)}/clinician-action`,
      {
        method: "POST",
        headers,
        cache: "no-store",
        body: JSON.stringify({
          claim_id: body.claimId,
          action: body.action.toLowerCase(),
          note: body.note ?? "",
          verdict_shown: body.verdictShown ?? null,
          action_id: body.actionId,
        }),
      },
    );
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
