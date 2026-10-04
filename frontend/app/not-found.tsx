import { EmptyState } from "../components/empty-state";

export default function NotFound() {
  return (
    <section className="route-state" aria-labelledby="not-found-heading">
      <EmptyState
        headingId="not-found-heading"
        title="A little off the path."
        description="This page isn’t here. Your quiet space is just a step away."
        action={<a className="button" href="/">Back to BOOH</a>}
      />
    </section>
  );
}
