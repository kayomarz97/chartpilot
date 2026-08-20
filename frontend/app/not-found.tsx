import Link from "next/link";

export default function NotFound() {
  return (
    <div className="container" style={{ padding: "3rem 0" }}>
      <h1>Patient not found</h1>
      <p>No chart preparation run exists for this patient identifier.</p>
      <Link href="/">Back to patient list</Link>
    </div>
  );
}
