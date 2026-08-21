import { notFound } from "next/navigation";
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
  if (!patient) {
    notFound();
  }
  // Server-resolved mock fallback guarantees an instant, always-valid
  // render; PatientDetailClient then attempts to swap in the live backend
  // run for this patient id (TD-011) without ever risking a broken page.
  return <PatientDetailClient patientId={id} fallback={patient} />;
}
