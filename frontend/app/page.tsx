import { EmptyState } from "../components/empty-state";

export default function HomePage() {
  return (
    <>
      <section className="welcome" aria-labelledby="welcome-heading">
        <div>
          <p className="eyebrow">A little room to rest</p>
          <h1 id="welcome-heading">How long do I<br />probably have?</h1>
          <p className="welcome-copy">
            One less thing to work out in the middle of the night.
          </p>
        </div>
        <div className="night-scene" aria-hidden="true">
          <svg viewBox="0 0 220 220" fill="none" focusable="false">
            <circle cx="110" cy="110" r="92" stroke="currentColor" strokeDasharray="2 9" />
            <path d="M133 57a53 53 0 1 0 30 85 58 58 0 0 1-30-85Z" fill="currentColor" />
            <path d="M171 52v14m-7-7h14M55 140v10m-5-5h10" stroke="currentColor" strokeLinecap="round" />
            <circle cx="63" cy="62" r="2" fill="currentColor" />
          </svg>
        </div>
      </section>

      <section className="estimate-space" aria-labelledby="estimate-heading">
        <div className="estimate-placeholder" aria-hidden="true">
          <span>—</span>
          <span className="eyebrow">Time to yourself</span>
        </div>
        <EmptyState
          headingId="estimate-heading"
          title="A quieter night starts here."
          description="Your next-wake estimate will have a home here. This is an early preview; no sleep history is connected yet."
        />
      </section>

      <aside className="gentle-note" aria-label="About future estimates">
        <span className="note-marker" aria-hidden="true" />
        <p>In time, a gentle estimate from your own history. Always a guide, never a guarantee.</p>
      </aside>
    </>
  );
}
