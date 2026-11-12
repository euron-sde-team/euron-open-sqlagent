import type { Metadata } from "next";

import { ConnectionsScreen } from "@/features/connections/components/connections-screen";

export const metadata: Metadata = { title: "Connections" };

export default function Page() {
  return <ConnectionsScreen />;
}
