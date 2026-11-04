import { Link } from "react-router-dom";

export function NotFoundPage() {
  return (
    <main id="main" className="page">
      <div className="board-note paper">
        <span className="pin pin--red board-note__pin" aria-hidden="true" />
        <h1 className="page-title page-title--ink">Nothing pinned here</h1>
        <p>This page isn’t on the board. It may have been taken down, or the link has a typo.</p>
        <Link className="btn btn--ink" to="/">
          Back to the board
        </Link>
      </div>
    </main>
  );
}
