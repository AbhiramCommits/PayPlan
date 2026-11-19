const styles = {
  ACTIVE: "chip chip-blue",
  COMPLETED: "chip chip-green",
  DELINQUENT: "chip chip-red",
  CANCELLED: "chip chip-gray",
  SCHEDULED: "chip chip-gray",
  DUE: "chip chip-amber",
  PAID: "chip chip-green",
  LATE: "chip chip-red",
  FAILED: "chip chip-red",
  WAIVED: "chip chip-purple",
  SUCCEEDED: "chip chip-green",
  REFUNDED: "chip chip-gray",
  PENDING: "chip chip-amber",
};

export default function StatusChip({ status }) {
  return <span className={styles[status] || "chip chip-gray"}>{status}</span>;
}
