import type { Metadata } from "next";

import { SchemaScreen } from "@/features/connections/components/schema-screen";

export const metadata: Metadata = { title: "Schema" };

export default async function Page({ params }: { params: Promise<{ cid: string }> }) {
  const { cid } = await params;
  return <SchemaScreen cid={cid} />;
}
