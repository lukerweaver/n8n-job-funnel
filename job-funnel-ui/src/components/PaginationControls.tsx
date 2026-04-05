interface PaginationControlsProps {
  total: number;
  limit: number;
  offset: number;
  onPageChange: (nextOffset: number) => void;
}

export function PaginationControls({
  total,
  limit,
  offset,
  onPageChange,
}: PaginationControlsProps) {
  const currentPage = Math.floor(offset / limit) + 1;
  const totalPages = Math.max(1, Math.ceil(total / limit));
  const pageStart = total === 0 ? 0 : offset + 1;
  const pageEnd = Math.min(offset + limit, total);

  return (
    <div className="pagination">
      <p className="pagination-summary">
        Showing {pageStart}-{pageEnd} of {total}
      </p>

      <div className="pagination-actions">
        <button type="button" onClick={() => onPageChange(Math.max(0, offset - limit))} disabled={offset === 0}>
          Previous
        </button>
        <span className="pagination-page">
          Page {currentPage} / {totalPages}
        </span>
        <button
          type="button"
          onClick={() => onPageChange(offset + limit)}
          disabled={offset + limit >= total}
        >
          Next
        </button>
      </div>
    </div>
  );
}
