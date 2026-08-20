import { notFound } from "next/navigation";
import { getPatientById, patients } from "@/lib/mockData";
import { PatientView } from "@/components/PatientView";

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
  return <PatientView patient={patient} />;
}
