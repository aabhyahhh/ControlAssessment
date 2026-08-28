import { LogOut, Plus, Trash2 } from "lucide-react";
import { useEffect, useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import BrandLogo from "../components/BrandLogo";
import { useAuth } from "../auth/AuthContext";
import { ApiError } from "../services/api";
import * as projectService from "../services/projectService";
import type { Framework, Project } from "../types";

const FRAMEWORK_LABELS: Record<Framework, string> = {
  generic: "Generic",
  sox: "SOX",
  itgc: "ITGC",
  iso27001: "ISO 27001",
};

function NewProjectModal({
  onClose,
  onCreated,
}: {
  onClose: () => void;
  onCreated: (project: Project) => void;
}) {
  const [name, setName] = useState("");
  const [framework, setFramework] = useState<Framework>("generic");
  const [auditStart, setAuditStart] = useState("");
  const [auditEnd, setAuditEnd] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setError(null);
    if (auditEnd < auditStart) {
      setError("Audit period end must be on or after the start date.");
      return;
    }
    setSubmitting(true);
    try {
      const project = await projectService.createProject({
        name,
        framework,
        audit_period_start: auditStart,
        audit_period_end: auditEnd,
      });
      onCreated(project);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not create project.");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal-card" onClick={(e) => e.stopPropagation()}>
        <h2>New Assessment Project</h2>
        <p className="modal-subtitle">
          The audit period drives the timeline-sufficiency check in Phase 3 — set it accurately.
        </p>
        <form onSubmit={handleSubmit} className="modal-form">
          <label className="field-label">
            Project name
            <input
              className="field-input"
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              required
              autoFocus
            />
          </label>
          <label className="field-label">
            Framework
            <select
              className="field-input"
              value={framework}
              onChange={(e) => setFramework(e.target.value as Framework)}
            >
              {Object.entries(FRAMEWORK_LABELS).map(([value, label]) => (
                <option key={value} value={value}>
                  {label}
                </option>
              ))}
            </select>
          </label>
          <div className="modal-form-row">
            <label className="field-label">
              Audit period start
              <input
                className="field-input"
                type="date"
                value={auditStart}
                onChange={(e) => setAuditStart(e.target.value)}
                required
              />
            </label>
            <label className="field-label">
              Audit period end
              <input
                className="field-input"
                type="date"
                value={auditEnd}
                onChange={(e) => setAuditEnd(e.target.value)}
                required
              />
            </label>
          </div>
          {error && <span className="field-error">{error}</span>}
          <div className="modal-actions">
            <button type="button" className="kpmg-btn ghost" onClick={onClose}>
              Cancel
            </button>
            <button type="submit" className="kpmg-btn primary" disabled={submitting}>
              {submitting ? "Creating…" : "Create project"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

/** Deleting a project destroys every phase result, uploaded file and export
 *  it owns, with no undo — so it gets an explicit confirmation naming the
 *  project, not a bare icon click. */
function DeleteProjectModal({
  project,
  onClose,
  onDeleted,
}: {
  project: Project;
  onClose: () => void;
  onDeleted: (projectId: string) => void;
}) {
  const [error, setError] = useState<string | null>(null);
  const [deleting, setDeleting] = useState(false);

  const handleDelete = async () => {
    setError(null);
    setDeleting(true);
    try {
      await projectService.deleteProject(project.id);
      onDeleted(project.id);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not delete this project.");
      setDeleting(false);
    }
  };

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal-card" onClick={(e) => e.stopPropagation()}>
        <h2>Delete this project?</h2>
        <p className="modal-subtitle">
          <strong>{project.name}</strong> and everything in it — the RACM, uploaded evidence and SOP, all
          phase results, testing attributes and generated reports — will be permanently deleted. This
          cannot be undone.
        </p>
        {error && <span className="field-error">{error}</span>}
        <div className="modal-actions">
          <button type="button" className="kpmg-btn ghost" onClick={onClose} disabled={deleting}>
            Cancel
          </button>
          <button type="button" className="kpmg-btn danger" onClick={handleDelete} disabled={deleting}>
            {deleting ? "Deleting…" : "Delete project"}
          </button>
        </div>
      </div>
    </div>
  );
}

const Projects = () => {
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  const [projects, setProjects] = useState<Project[] | null>(null);
  const [showModal, setShowModal] = useState(false);
  const [pendingDelete, setPendingDelete] = useState<Project | null>(null);

  useEffect(() => {
    projectService.listProjects().then(setProjects);
  }, []);

  return (
    <div className="projects-page">
      <header className="projects-header">
        <div className="landing-brand">
          <BrandLogo className="kpmg-logo-img" />
          <span className="brand-separator" />
          <span className="brand-product-name">ControlAssessment</span>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 14 }}>
          <span style={{ color: "var(--muted)", fontSize: 13.5 }}>{user?.email}</span>
          <button className="kpmg-btn ghost" onClick={logout}>
            <LogOut size={15} />
            Log out
          </button>
        </div>
      </header>

      <main className="projects-main">
        <div className="projects-main-head">
          <div>
            <h1>Your Assessment Projects</h1>
            <p>Pick a project to continue, or start a new engagement.</p>
          </div>
          <button className="kpmg-btn primary" onClick={() => setShowModal(true)}>
            <Plus size={16} />
            New Project
          </button>
        </div>

        {projects === null && <p style={{ color: "var(--muted)" }}>Loading…</p>}

        {projects !== null && projects.length === 0 && (
          <div className="projects-empty">
            <p>No projects yet. Create one to begin a control assessment.</p>
          </div>
        )}

        {projects !== null && projects.length > 0 && (
          <div className="projects-grid">
            {projects.map((project) => (
              <div
                key={project.id}
                className="project-card"
                onClick={() => navigate(`/workspace/${project.id}`)}
              >
                <span className="project-card-framework">{FRAMEWORK_LABELS[project.framework]}</span>
                <button
                  type="button"
                  className="project-card-delete"
                  title={`Delete "${project.name}"`}
                  aria-label={`Delete project ${project.name}`}
                  onClick={(e) => {
                    // The whole card navigates on click, so without this the
                    // delete button would open the workspace instead.
                    e.stopPropagation();
                    setPendingDelete(project);
                  }}
                >
                  <Trash2 size={15} />
                </button>
                <h3>{project.name}</h3>
                <div className="project-card-meta">
                  <span>
                    Audit period: {project.audit_period_start} → {project.audit_period_end}
                  </span>
                  <span>Phase {project.current_phase} of 4</span>
                </div>
              </div>
            ))}
          </div>
        )}
      </main>

      {showModal && (
        <NewProjectModal
          onClose={() => setShowModal(false)}
          onCreated={(project) => {
            setShowModal(false);
            setProjects((prev) => [project, ...(prev ?? [])]);
            navigate(`/workspace/${project.id}`);
          }}
        />
      )}

      {pendingDelete && (
        <DeleteProjectModal
          project={pendingDelete}
          onClose={() => setPendingDelete(null)}
          onDeleted={(projectId) => {
            setPendingDelete(null);
            setProjects((prev) => (prev ?? []).filter((p) => p.id !== projectId));
          }}
        />
      )}
    </div>
  );
};

export default Projects;
