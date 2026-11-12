import type { Metadata } from "next";

import { TemplatesScreen } from "@/features/templates/components/templates-screen";

export const metadata: Metadata = { title: "Templates" };

export default function Page() {
  return <TemplatesScreen />;
}
