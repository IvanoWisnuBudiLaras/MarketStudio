import type { Metadata } from "next";
import type { ReactNode } from "react";
import "@astryxdesign/core/astryx.css";
import "./style.css";

export const metadata: Metadata = { title: "Business Studio | MarketStudio" };

export default function Layout({ children }: { children: ReactNode }) {
  return <html lang="id"><body>{children}</body></html>;
}
