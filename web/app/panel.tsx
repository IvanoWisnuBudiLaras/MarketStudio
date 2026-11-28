import { Card } from "@astryxdesign/core/Card";
import type { ReactNode } from "react";

export function Panel({ title, children }: { title: string; children: ReactNode }) {
  return <section><Card className="business-panel" padding={0}><h2>{title}</h2>{children}</Card></section>;
}
