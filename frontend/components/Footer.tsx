import styles from "./Footer.module.css";

export function Footer() {
  return (
    <footer className={styles.footer}>
      <div className={`container ${styles.inner}`}>
        <p>
          ChartPilot reuses UI components and interaction patterns from Iatronix — disclosed.
        </p>
        <p>All patient names, identifiers, and clinical data shown are synthetic demo content.</p>
      </div>
    </footer>
  );
}
