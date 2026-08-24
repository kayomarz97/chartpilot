import { getPatientById, patients } from "@/lib/mockData";
import { PatientDetailClient } from "@/components/PatientDetailClient";

export function generateStaticParams() {
  return patients.map((p) => ({ id: p.patientId }));
}

export default async function PatientPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  const patient = getPatientById(id);
  // Server-resolved mock fallback guarantees an instant, always-valid
  // render for the bundled demo ids; PatientDetailClient then attempts to
  // swap in the live backend run for this patient id (TD-011). Live-only
  // ids (e.g. patient-a..patient-e) have no mock fallback — `patient` is
  // undefined for those, and PatientDetailClient renders entirely from the
  // live fetch instead of 404ing (relies on the App Router's default
  // `dynamicParams = true`; not set to false anywhere in this project, and
  // next.config.ts uses `output: "standalone"`, not `"export"`).
  return <PatientDetailClient patientId={id} fallback={patient ?? null} />;
}
