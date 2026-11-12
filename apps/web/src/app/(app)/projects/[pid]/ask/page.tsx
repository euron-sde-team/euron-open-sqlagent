import type { Metadata } from "next";
import { Suspense } from "react";

import { AskScreen } from "@/features/ask/components/ask-screen";

export const metadata: Metadata = { title: "Ask" };

export default function Page() {
  return (
    <Suspense>
      <AskScreen />
    </Suspense>
  );
}
