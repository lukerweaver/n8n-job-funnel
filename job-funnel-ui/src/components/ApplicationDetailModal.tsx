import { useEffect, useMemo, useState } from "react";

import {
  createInterviewRound,
  deleteInterviewRound,
  getApplication,
  getInterviewRounds,
  updateApplicationLifecycleDates,
  updateApplicationStatus,
  updateInterviewRound,
} from "../api";
import type { ApplicationStatus, InterviewRound, InterviewRoundStatus, JobApplication } from "../types";
import { formatDate, formatDateOnly, moneyRange, renderListish } from "../utils";
import { DetailModal } from "./DetailModal";

const STATUS_LABELS: Record<ApplicationStatus, string> = {
  new: "New",
  scored: "Scored",
  tailored: "Tailored",
  notified: "Notified",
  applied: "Applied",
  screening: "Screening",
  interview: "Interview",
  offer: "Offer",
  rejected: "Rejected",
  ghosted: "Ghosted",
  withdrawn: "Withdrawn",
  pass: "Pass",
};

const TRANSITIONS: Partial<Record<ApplicationStatus, ApplicationStatus[]>> = {
  new: ["applied", "pass"],
  scored: ["applied", "pass"],
  tailored: ["applied", "pass"],
  notified: ["applied", "pass"],
  applied: ["screening", "interview", "offer", "rejected", "ghosted", "withdrawn", "pass"],
  screening: ["interview", "offer", "rejected", "ghosted", "withdrawn", "pass"],
  interview: ["offer", "rejected", "ghosted", "withdrawn", "pass"],
};

interface InterviewRoundFormState {
  round_number: string;
  stage_name: string;
  status: InterviewRoundStatus;
  scheduled_at: string;
  completed_at: string;
  notes: string;
}

type LifecycleDateField =
  | "applied_at"
  | "screening_at"
  | "offer_at"
  | "rejected_at"
  | "ghosted_at"
  | "withdrawn_at"
  | "passed_at";

type LifecycleNoteField =
  | "applied_notes"
  | "screening_notes"
  | "offer_notes"
  | "rejected_notes"
  | "ghosted_notes"
  | "withdrawn_notes"
  | "passed_notes";

interface LifecycleMilestone {
  status: ApplicationStatus;
  label: string;
  field: LifecycleDateField;
  noteField: LifecycleNoteField;
}

const EMPTY_ROUND_FORM: InterviewRoundFormState = {
  round_number: "",
  stage_name: "",
  status: "scheduled",
  scheduled_at: "",
  completed_at: "",
  notes: "",
};

interface ApplicationDetailModalProps {
  applicationId: number;
  fallbackTitle: string;
  fallbackSubtitle: string;
  onClose: () => void;
  onPrevious?: () => void;
  onNext?: () => void;
  previousDisabled?: boolean;
  nextDisabled?: boolean;
  onApplicationUpdated?: (application: JobApplication) => void;
}

function toInputDateTime(value: string | null) {
  return toInputDate(value);
}

function toInputDate(value: string | null) {
  if (!value) {
    return "";
  }
  const date = new Date(value);
  const pad = (part: number) => String(part).padStart(2, "0");
  return `${date.getUTCFullYear()}-${pad(date.getUTCMonth() + 1)}-${pad(date.getUTCDate())}`;
}

function toIsoOrNull(value: string) {
  return value ? `${value}T00:00:00Z` : null;
}

function todayDateString() {
  return toInputDate(new Date().toISOString());
}

function buildRoundForm(round?: InterviewRound): InterviewRoundFormState {
  if (!round) {
    return EMPTY_ROUND_FORM;
  }
  return {
    round_number: String(round.round_number),
    stage_name: round.stage_name ?? "",
    status: round.status,
    scheduled_at: toInputDateTime(round.scheduled_at),
    completed_at: toInputDateTime(round.completed_at),
    notes: round.notes ?? "",
  };
}

export function ApplicationDetailModal({
  applicationId,
  fallbackTitle,
  fallbackSubtitle,
  onClose,
  onPrevious,
  onNext,
  previousDisabled = false,
  nextDisabled = false,
  onApplicationUpdated,
}: ApplicationDetailModalProps) {
  const lifecycleMilestones: LifecycleMilestone[] = [
    { status: "applied", label: "Applied", field: "applied_at", noteField: "applied_notes" },
    { status: "screening", label: "Screening", field: "screening_at", noteField: "screening_notes" },
    { status: "offer", label: "Offer", field: "offer_at", noteField: "offer_notes" },
    { status: "rejected", label: "Rejected", field: "rejected_at", noteField: "rejected_notes" },
    { status: "ghosted", label: "Ghosted", field: "ghosted_at", noteField: "ghosted_notes" },
    { status: "withdrawn", label: "Withdrawn", field: "withdrawn_at", noteField: "withdrawn_notes" },
    { status: "pass", label: "Pass", field: "passed_at", noteField: "passed_notes" },
  ];

  const [application, setApplication] = useState<JobApplication | null>(null);
  const [interviewRounds, setInterviewRounds] = useState<InterviewRound[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [copyState, setCopyState] = useState<"idle" | "copied" | "error">("idle");
  const [statusSubmitting, setStatusSubmitting] = useState<ApplicationStatus | null>(null);
  const [actionDate, setActionDate] = useState(todayDateString());
  const [actionNote, setActionNote] = useState("");
  const [editingLifecycleStatus, setEditingLifecycleStatus] = useState<ApplicationStatus | null>(null);
  const [lifecycleDate, setLifecycleDate] = useState("");
  const [lifecycleNote, setLifecycleNote] = useState("");
  const [lifecycleSubmitting, setLifecycleSubmitting] = useState(false);
  const [editingRoundId, setEditingRoundId] = useState<number | null>(null);
  const [roundForm, setRoundForm] = useState<InterviewRoundFormState>(EMPTY_ROUND_FORM);
  const [roundSubmitError, setRoundSubmitError] = useState<string | null>(null);
  const [roundSubmitting, setRoundSubmitting] = useState(false);
  const [deletingRoundId, setDeletingRoundId] = useState<number | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    setCopyState("idle");
    setEditingRoundId(null);
    setRoundForm(EMPTY_ROUND_FORM);

    Promise.all([getApplication(applicationId), getInterviewRounds(applicationId)])
      .then(([applicationResponse, roundsResponse]) => {
        if (cancelled) {
          return;
        }
        setApplication(applicationResponse);
        setInterviewRounds(roundsResponse.items);
        setActionDate(todayDateString());
        setActionNote("");
      })
      .catch((requestError: Error) => {
        if (!cancelled) {
          setError(requestError.message);
        }
      })
      .finally(() => {
        if (!cancelled) {
          setLoading(false);
        }
      });

    return () => {
      cancelled = true;
    };
  }, [applicationId]);

  const availableTransitions = useMemo(() => {
    if (!application) {
      return [];
    }
    return TRANSITIONS[application.status] ?? [];
  }, [application]);

  const showInterviewRounds = useMemo(() => {
    if (!application) {
      return false;
    }
    return ["applied", "screening", "interview", "offer", "rejected", "ghosted", "withdrawn", "pass"].includes(
      application.status,
    );
  }, [application]);

  const visibleLifecycleMilestones = useMemo(() => {
    if (!application) {
      return [];
    }
    return lifecycleMilestones.filter((milestone) => Boolean(application[milestone.field]));
  }, [application]);

  async function refreshApplication() {
    const [applicationResponse, roundsResponse] = await Promise.all([
      getApplication(applicationId),
      getInterviewRounds(applicationId),
    ]);
    setApplication(applicationResponse);
    setInterviewRounds(roundsResponse.items);
    onApplicationUpdated?.(applicationResponse);
  }

  async function handleCopyDescription() {
    if (!application?.description) {
      setCopyState("error");
      return;
    }

    try {
      await navigator.clipboard.writeText(application.description);
      setCopyState("copied");
    } catch {
      setCopyState("error");
    }
  }

  async function handleStatusUpdate(status: ApplicationStatus) {
    setStatusSubmitting(status);
    setError(null);
    try {
      const lifecyclePayload: {
        status: ApplicationStatus;
        applied_at?: string | null;
        applied_notes?: string | null;
        screening_at?: string | null;
        screening_notes?: string | null;
        offer_at?: string | null;
        offer_notes?: string | null;
        rejected_at?: string | null;
        rejected_notes?: string | null;
        ghosted_at?: string | null;
        ghosted_notes?: string | null;
        withdrawn_at?: string | null;
        withdrawn_notes?: string | null;
        passed_at?: string | null;
        passed_notes?: string | null;
      } = { status };
      const milestone = lifecycleMilestones.find((item) => item.status === status);
      if (milestone && actionDate) {
        lifecyclePayload[milestone.field] = toIsoOrNull(actionDate);
        lifecyclePayload[milestone.noteField] = actionNote.trim() || null;
      }
      const updated = await updateApplicationStatus(applicationId, lifecyclePayload);
      setApplication(updated);
      onApplicationUpdated?.(updated);
      setEditingLifecycleStatus(null);
      setActionNote("");
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "Unable to update application status.");
    } finally {
      setStatusSubmitting(null);
    }
  }

  function startEditLifecycleDate(status: ApplicationStatus, value: string | null, note: string | null) {
    setEditingLifecycleStatus(status);
    setLifecycleDate(toInputDate(value));
    setLifecycleNote(note ?? "");
  }

  async function handleLifecycleDateSave(field: LifecycleDateField, noteField: LifecycleNoteField) {
    setLifecycleSubmitting(true);
    setError(null);
    try {
      const updated = await updateApplicationLifecycleDates(applicationId, {
        [field]: toIsoOrNull(lifecycleDate),
        [noteField]: lifecycleNote.trim() || null,
      });
      setApplication(updated);
      onApplicationUpdated?.(updated);
      setEditingLifecycleStatus(null);
      setLifecycleDate("");
      setLifecycleNote("");
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "Unable to update lifecycle date.");
    } finally {
      setLifecycleSubmitting(false);
    }
  }

  function startCreateRound() {
    setEditingRoundId(null);
    setRoundForm(EMPTY_ROUND_FORM);
    setRoundSubmitError(null);
  }

  function startEditRound(round: InterviewRound) {
    setEditingRoundId(round.id);
    setRoundForm(buildRoundForm(round));
    setRoundSubmitError(null);
  }

  async function handleRoundSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setRoundSubmitting(true);
    setRoundSubmitError(null);

    const payload = {
      round_number: Number(roundForm.round_number),
      stage_name: roundForm.stage_name.trim() || null,
      status: roundForm.status,
      scheduled_at: toIsoOrNull(roundForm.scheduled_at),
      completed_at: toIsoOrNull(roundForm.completed_at),
      notes: roundForm.notes.trim() || null,
    };

    try {
      if (editingRoundId === null) {
        await createInterviewRound(applicationId, payload);
      } else {
        await updateInterviewRound(applicationId, editingRoundId, payload);
      }
      await refreshApplication();
      setEditingRoundId(null);
      setRoundForm(EMPTY_ROUND_FORM);
    } catch (requestError) {
      setRoundSubmitError(requestError instanceof Error ? requestError.message : "Unable to save interview round.");
    } finally {
      setRoundSubmitting(false);
    }
  }

  async function handleRoundDelete(interviewRoundId: number) {
    setDeletingRoundId(interviewRoundId);
    setRoundSubmitError(null);
    try {
      await deleteInterviewRound(applicationId, interviewRoundId);
      await refreshApplication();
      if (editingRoundId === interviewRoundId) {
        setEditingRoundId(null);
        setRoundForm(EMPTY_ROUND_FORM);
      }
    } catch (requestError) {
      setRoundSubmitError(requestError instanceof Error ? requestError.message : "Unable to delete interview round.");
    } finally {
      setDeletingRoundId(null);
    }
  }

  return (
    <DetailModal
      title={application?.title ?? fallbackTitle}
      subtitle={application ? `Application #${application.id} · ${application.company_name ?? "Unknown company"}` : fallbackSubtitle}
      onClose={onClose}
      onPrevious={onPrevious}
      onNext={onNext}
      previousDisabled={previousDisabled}
      nextDisabled={nextDisabled}
    >
      {loading ? <p className="state-message">Loading application details...</p> : null}
      {error ? <p className="state-message error-message">{error}</p> : null}

      {!loading && !error && application ? (
        <>
          <div className="detail-section">
            <h4>Summary</h4>
            <dl className="detail-list detail-grid">
              <div>
                <dt>Status</dt>
                <dd>
                  <span className={`status-pill status-${application.status}`}>{application.status}</span>
                </dd>
              </div>
              <div>
                <dt>Score</dt>
                <dd>{application.score ?? "N/A"}</dd>
              </div>
              <div>
                <dt>Screening</dt>
                <dd>{application.screening_likelihood ?? "N/A"}</dd>
              </div>
              <div>
                <dt>Recommendation</dt>
                <dd>{application.recommendation ?? "N/A"}</dd>
              </div>
              <div>
                <dt>Compensation</dt>
                <dd>{moneyRange(application.yearly_min_compensation, application.yearly_max_compensation)}</dd>
              </div>
              <div>
                <dt>Next Interview</dt>
                <dd>
                  {application.next_interview_at
                    ? `${formatDate(application.next_interview_at)}${application.next_interview_stage ? ` · ${application.next_interview_stage}` : ""}`
                    : "N/A"}
                </dd>
              </div>
            </dl>
          </div>

          <div className="detail-section">
            <h4>Lifecycle</h4>
            {availableTransitions.length > 0 ? (
              <>
                <div className="lifecycle-action-bar">
                  <label>
                    Effective Date
                    <input type="date" value={actionDate} onChange={(event) => setActionDate(event.target.value)} />
                  </label>
                  <label className="lifecycle-note-field">
                    Event Note
                    <textarea
                      className="editor-textarea editor-textarea-compact"
                      value={actionNote}
                      onChange={(event) => setActionNote(event.target.value)}
                      placeholder="Optional note for the selected lifecycle event."
                    />
                  </label>
                </div>
                <div className="workflow-actions">
                  {availableTransitions.map((status) => (
                    <button
                      key={status}
                      type="button"
                      className={`action-button ${status === "rejected" || status === "ghosted" || status === "withdrawn" || status === "pass" ? "danger-button" : ""}`}
                      onClick={() => handleStatusUpdate(status)}
                      disabled={statusSubmitting !== null}
                    >
                      {statusSubmitting === status ? "Saving..." : `Mark ${STATUS_LABELS[status]}`}
                    </button>
                  ))}
                </div>
              </>
            ) : (
              <p className="state-message compact-state-message">No further guided actions.</p>
            )}
            {visibleLifecycleMilestones.length > 0 ? (
              <div className="lifecycle-milestones">
                {visibleLifecycleMilestones.map((milestone) => (
                  <div key={milestone.status} className="lifecycle-milestone-row">
                    <div>
                      <strong>{milestone.label}</strong>
                      <p>{formatDateOnly(application[milestone.field])}</p>
                      <p>{application[milestone.noteField] ?? "No notes."}</p>
                    </div>
                    {editingLifecycleStatus === milestone.status ? (
                      <div className="lifecycle-edit-panel">
                        <input
                          type="date"
                          value={lifecycleDate}
                          onChange={(event) => setLifecycleDate(event.target.value)}
                        />
                        <textarea
                          className="editor-textarea editor-textarea-compact"
                          value={lifecycleNote}
                          onChange={(event) => setLifecycleNote(event.target.value)}
                          placeholder="Update lifecycle note"
                        />
                        <button
                          type="button"
                          className="action-button"
                          onClick={() => handleLifecycleDateSave(milestone.field, milestone.noteField)}
                          disabled={lifecycleSubmitting}
                        >
                          {lifecycleSubmitting ? "Saving..." : "Save"}
                        </button>
                        <button
                          type="button"
                          className="ghost-button"
                          onClick={() => {
                            setEditingLifecycleStatus(null);
                            setLifecycleDate("");
                            setLifecycleNote("");
                          }}
                        >
                          Cancel
                        </button>
                      </div>
                    ) : (
                      <button
                        type="button"
                        className="action-button"
                        onClick={() =>
                          startEditLifecycleDate(
                            milestone.status,
                            application[milestone.field],
                            application[milestone.noteField],
                          )
                        }
                      >
                        Edit
                      </button>
                    )}
                  </div>
                ))}
              </div>
            ) : null}
          </div>

          {showInterviewRounds ? (
            <div className="detail-section">
              <h4>Interview Rounds</h4>
              {roundSubmitError ? <p className="error-callout">{roundSubmitError}</p> : null}
              <div className="interview-rounds">
                {interviewRounds.length === 0 ? <p>No interview rounds yet.</p> : null}
                {interviewRounds.map((round) => (
                  <div key={round.id} className="round-card">
                    <div className="round-card-header">
                      <div>
                        <strong>Round {round.round_number}</strong>
                        {round.stage_name ? <p>{round.stage_name}</p> : null}
                      </div>
                      <span className={`status-pill status-${round.status}`}>{round.status}</span>
                    </div>
                    <p className="round-meta">
                      Scheduled: {formatDateOnly(round.scheduled_at)} | Completed: {formatDateOnly(round.completed_at)}
                    </p>
                    <p>{round.notes ?? "No notes."}</p>
                    <div className="detail-actions">
                      <button type="button" className="action-button" onClick={() => startEditRound(round)}>
                        Edit Round
                      </button>
                      <button
                        type="button"
                        className="action-button danger-button"
                        onClick={() => handleRoundDelete(round.id)}
                        disabled={deletingRoundId === round.id}
                      >
                        {deletingRoundId === round.id ? "Deleting..." : "Delete Round"}
                      </button>
                    </div>
                  </div>
                ))}
              </div>

              <form className="editor-form interview-round-form" onSubmit={handleRoundSubmit}>
                <div className="round-form-header">
                  <h5>{editingRoundId === null ? "Add Interview Round" : `Edit Round #${roundForm.round_number}`}</h5>
                  {editingRoundId !== null ? (
                    <button type="button" className="ghost-button" onClick={startCreateRound}>
                      New Round
                    </button>
                  ) : null}
                </div>

                <div className="inline-form-grid">
                  <label>
                    Round Number
                    <input
                      type="number"
                      min="1"
                      required
                      value={roundForm.round_number}
                      onChange={(event) => setRoundForm((current) => ({ ...current, round_number: event.target.value }))}
                    />
                  </label>
                  <label>
                    Status
                    <select
                      value={roundForm.status}
                      onChange={(event) =>
                        setRoundForm((current) => ({ ...current, status: event.target.value as InterviewRoundStatus }))
                      }
                    >
                      <option value="scheduled">scheduled</option>
                      <option value="completed">completed</option>
                    </select>
                  </label>
                  <label>
                    Stage Name
                    <input
                      type="text"
                      value={roundForm.stage_name}
                      onChange={(event) => setRoundForm((current) => ({ ...current, stage_name: event.target.value }))}
                      placeholder="Hiring Manager"
                    />
                  </label>
                  <label>
                    Scheduled At
                    <input
                      type="date"
                      value={roundForm.scheduled_at}
                      onChange={(event) => setRoundForm((current) => ({ ...current, scheduled_at: event.target.value }))}
                    />
                  </label>
                  <label>
                    Completed At
                    <input
                      type="date"
                      value={roundForm.completed_at}
                      onChange={(event) => setRoundForm((current) => ({ ...current, completed_at: event.target.value }))}
                    />
                  </label>
                </div>

                <label>
                  Notes
                  <textarea
                    className="editor-textarea editor-textarea-compact"
                    value={roundForm.notes}
                    onChange={(event) => setRoundForm((current) => ({ ...current, notes: event.target.value }))}
                    placeholder="Capture prep, feedback, and takeaways."
                  />
                </label>

                <div className="form-actions">
                  <button type="submit" className="primary-button" disabled={roundSubmitting}>
                    {roundSubmitting ? "Saving..." : editingRoundId === null ? "Add Round" : "Save Round"}
                  </button>
                </div>
              </form>
            </div>
          ) : null}

          <div className="detail-section">
            <h4>Rationale</h4>
            <p>{application.justification ?? "No justification captured."}</p>
            <p><strong>Gating flags:</strong> {renderListish(application.gating_flags)}</p>
            <p><strong>Strengths:</strong> {renderListish(application.strengths)}</p>
            <p><strong>Gaps:</strong> {renderListish(application.gaps)}</p>
          </div>

          <div className="detail-section">
            <h4>Metadata</h4>
            <dl className="detail-list detail-grid">
              <div>
                <dt>Job ID</dt>
                <dd className="mono">{application.job_id ?? "N/A"}</dd>
              </div>
              <div>
                <dt>Classification</dt>
                <dd>{application.classification_key ?? "N/A"}</dd>
              </div>
              <div>
                <dt>Resume</dt>
                <dd>{application.resume_name ?? "N/A"}</dd>
              </div>
              <div>
                <dt>Applied At</dt>
                <dd>{formatDateOnly(application.applied_at)}</dd>
              </div>
            </dl>
            <div className="detail-actions">
              {application.apply_url ? (
                <a className="action-button" href={application.apply_url} target="_blank" rel="noreferrer">
                  Open Apply URL
                </a>
              ) : null}
              <button type="button" className="action-button" onClick={handleCopyDescription} disabled={!application.description}>
                Copy Job Description
              </button>
              {copyState === "copied" ? <span className="inline-feedback">Copied.</span> : null}
              {copyState === "error" ? <span className="inline-feedback error-text">Unable to copy.</span> : null}
            </div>
          </div>
        </>
      ) : null}
    </DetailModal>
  );
}
