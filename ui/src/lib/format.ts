const STATUS: Record<string, string> = {
  published: "Yayında",
  draft: "Taslak",
  deleted: "Silindi",
  pending: "Bekliyor",
  running: "Çalışıyor",
  succeeded: "Başarılı",
  failed: "Başarısız",
  needs_review: "İnceleme",
  cancelled: "İptal",
  paused: "Durduruldu",
};

export function statusLabel(status: string): string {
  return STATUS[status] || status;
}

export function formatNumber(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  return new Intl.NumberFormat("tr-TR").format(value);
}

export function formatWhen(value: string | null | undefined): string {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "—";
  return new Intl.DateTimeFormat("tr-TR", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(date);
}

export function formatDuration(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined) return "—";
  if (seconds < 60) return `${Math.round(seconds)} sn`;
  const minutes = Math.floor(seconds / 60);
  const rest = Math.round(seconds % 60);
  return `${minutes} dk ${rest} sn`;
}

export function dayLabel(iso: string): string {
  const [, month, day] = iso.split("-");
  return `${day}.${month}`;
}
