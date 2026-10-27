import { useRef, useState } from "react";

export function useBusy() {
  const lock = useRef(new Set<string>());
  const [busy, setBusy] = useState<ReadonlySet<string>>(new Set());

  async function run(id: string, task: () => Promise<void>) {
    if (lock.current.has(id)) return;
    lock.current.add(id);
    setBusy(new Set(lock.current));
    try {
      await task();
    } finally {
      lock.current.delete(id);
      setBusy(new Set(lock.current));
    }
  }

  return { busy, run, pending: (id: string) => busy.has(id) };
}
