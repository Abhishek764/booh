"use client";

import { Button } from "../components/button";
import { EmptyState } from "../components/empty-state";

export default function ErrorPage({ reset }: { error: Error; reset: () => void }) {
  return (
    <section className="route-state" role="alert" aria-labelledby="error-heading">
      <EmptyState
        headingId="error-heading"
        title="Let’s try that again."
        description="This view couldn’t load. Take a moment, then try again."
        action={<Button onClick={reset}>Try again</Button>}
      />
    </section>
  );
}
