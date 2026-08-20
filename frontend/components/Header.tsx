import Link from "next/link";
import styles from "./Header.module.css";
import { ShapeIcon } from "./icons";

export function Header() {
  return (
    <header className={styles.header}>
      <div className={`container ${styles.bar}`}>
        <Link href="/" className={styles.brand} aria-label="ChartPilot home">
          <span className={styles.brandMark} aria-hidden="true">
            CP
          </span>
          <span className={styles.brandName}>ChartPilot</span>
          <span className={styles.brandTag}>Pre-clinic chart preparation</span>
        </Link>
      </div>
      <div className={styles.banner}>
        <div className={`container ${styles.bannerInner}`}>
          <ShapeIcon shape="help-circle" />
          <span>Synthetic data — not for clinical use</span>
        </div>
      </div>
    </header>
  );
}
