/**
 * Admin console entry point. Lazily loaded (TDD §10.1).
 *
 * The floor-plan EDITOR is the same component as the viewer with
 * `editable` set -- that equivalence is the payoff from the single-codebase
 * decision (TDD §9.5), and it is why this file is small.
 */
export default function AdminConsole() {
  return (
    <section>
      <h1>Admin console</h1>
      <p>Phase 0 placeholder. Floor-plan editor reuses FloorPlan with editable.</p>
    </section>
  );
}
